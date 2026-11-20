/**
 * @title Deye SG02LP1 example: proxy.js + passive virtual components
 * @description OPTIONAL EXAMPLE, not required for the shelly_modbus
 * transport itself (see proxy.js for the minimal, brand-agnostic version).
 * This variant additionally mirrors a handful of readings into Shelly
 * virtual components, useful if you want a few key values available
 * locally on the Shelly's own web UI/app without depending on Home
 * Assistant being up.
 *
 * No independent polling loop: since ha-solarman already reads the full
 * register set periodically through this same proxy, number:200-208 are
 * updated passively by snooping on read responses that happen to pass
 * through - no duplicate UART traffic, no contention with ha-solarman's
 * own polling.
 *
 * Requires number:200 through number:208 to exist before startup (create
 * them under Settings > Components on the Shelly first).
 *
 * HTTP proxy contract:
 *   POST http://<shelly-ip>/script/<id>/modbus
 *   Body: hex-encoded Modbus RTU request, CRC16 included
 *   Response 200: {"resp": "<hex-encoded raw RTU response, CRC16 included>"}
 *   Response 429: {"error": "busy"}     - a transaction is already in flight
 *   Response 504: {"error": "timeout"}  - no response from the bus
 *   Response 400: {"error": "bad_request"}
 */

var CONFIG = {
  BAUD_RATE: 9600,
  MODE: "8N1",
  RESPONSE_TIMEOUT: 1000,
  HTTP_ENDPOINT_NAME: "modbus",
  DEBUG: true
};

var ENTITIES = [
  { name: "Total Power", units: "W", addr: 175, signed: true,
    scale: 1, vc: "number:200" },
  { name: "Battery Power", units: "W", addr: 190, signed: true,
    scale: 1, vc: "number:201" },
  { name: "PV1 Power", units: "W", addr: 186, signed: false,
    scale: 1, vc: "number:202" },
  { name: "Total Grid Power", units: "W", addr: 169, signed: true,
    scale: 10, vc: "number:203" },
  { name: "Battery SOC", units: "%", addr: 184, signed: false,
    scale: 1, vc: "number:204" },
  { name: "PV1 Voltage", units: "V", addr: 109, signed: false,
    scale: 0.1, vc: "number:205" },
  { name: "Grid Voltage L1", units: "V", addr: 150, signed: false,
    scale: 0.1, vc: "number:206" },
  { name: "Current L1", units: "A", addr: 164, signed: true,
    scale: 0.01, vc: "number:207" },
  { name: "AC Frequency", units: "Hz", addr: 192, signed: false,
    scale: 0.01, vc: "number:208" }
];

var state = {
  uart: null,
  rx: [],
  pending: null,
  responseTimer: null
};

function log(message) {
  if (CONFIG.DEBUG) print("[DEYE] " + message);
}

function bytesToString(bytes) {
  var value = "";
  var i;

  for (i = 0; i < bytes.length; i++) {
    value += String.fromCharCode(bytes[i] & 0xFF);
  }
  return value;
}

function hexToBytes(hex) {
  var bytes = [];
  var i;

  if (hex.length % 2 !== 0) return null;
  for (i = 0; i < hex.length; i += 2) {
    bytes.push(parseInt(hex.substr(i, 2), 16));
  }
  return bytes;
}

function bytesToHex(bytes) {
  var hex = "";
  var i;
  var b;

  for (i = 0; i < bytes.length; i++) {
    b = bytes[i].toString(16);
    if (b.length < 2) b = "0" + b;
    hex += b;
  }
  return hex;
}

function signed16(value) {
  return value >= 0x8000 ? value - 0x10000 : value;
}

function clearResponseTimer() {
  if (state.responseTimer !== null) {
    Timer.clear(state.responseTimer);
    state.responseTimer = null;
  }
}

function finishRequest(error, bytes) {
  var callback;

  if (state.pending === null) return;
  callback = state.pending.callback;
  state.pending = null;
  state.rx = [];
  clearResponseTimer();
  callback(error, bytes);
}

// Modbus RTU has no explicit length prefix; a fixed silence window after the
// last byte marks end-of-frame.
function onReceive(data) {
  var i;

  if (!data) return;
  for (i = 0; i < data.length; i++) {
    state.rx.push(data.charCodeAt(i) & 0xFF);
  }
  clearResponseTimer();
  state.responseTimer = Timer.set(50, false, function () {
    finishRequest(null, state.rx.slice(0));
  });
}

function sendRawRequest(bytes, callback) {
  if (state.pending !== null) {
    callback("busy", null);
    return;
  }

  state.pending = { callback: callback };
  state.rx = [];
  state.responseTimer = Timer.set(CONFIG.RESPONSE_TIMEOUT, false, function () {
    finishRequest("timeout", null);
  });
  state.uart.write(bytesToString(bytes));
}

// If this was a "read holding registers" (function 0x03) request and its
// response covers one of our tracked addresses, update that virtual
// component from the same data - no extra UART traffic needed.
function updateVirtualComponentsFromExchange(reqBytes, respBytes) {
  var func = reqBytes[1];
  var startAddr;
  var count;
  var byteCount;
  var i;
  var entity;
  var offset;
  var raw;
  var value;

  if (func !== 0x03) return;
  startAddr = (reqBytes[2] << 8) | reqBytes[3];
  count = (reqBytes[4] << 8) | reqBytes[5];
  if (respBytes.length < 3 || (respBytes[1] & 0x80)) return; // exception response
  byteCount = respBytes[2];
  if (respBytes.length < 3 + byteCount) return;

  for (i = 0; i < ENTITIES.length; i++) {
    entity = ENTITIES[i];
    if (entity.addr < startAddr || entity.addr >= startAddr + count) continue;
    offset = 3 + (entity.addr - startAddr) * 2;
    raw = (respBytes[offset] << 8) | respBytes[offset + 1];
    value = entity.signed ? signed16(raw) : raw;
    value = value * entity.scale;
    entity.handle.setValue(value);
    log(entity.name + ": " + value + " " + entity.units + " (passive)");
  }
}

function handleModbusEndpoint(request, response) {
  var bytes;

  if (!request.body) {
    response.code = 400;
    response.headers = [["Content-Type", "application/json"]];
    response.body = JSON.stringify({ error: "bad_request" });
    response.send();
    return;
  }

  bytes = hexToBytes(request.body.trim());
  if (bytes === null || bytes.length < 4) {
    response.code = 400;
    response.headers = [["Content-Type", "application/json"]];
    response.body = JSON.stringify({ error: "bad_request" });
    response.send();
    return;
  }

  sendRawRequest(bytes, function (error, respBytes) {
    response.headers = [["Content-Type", "application/json"]];
    if (error !== null) {
      response.code = error === "busy" ? 429 : 504;
      response.body = JSON.stringify({ error: error });
    } else {
      response.code = 200;
      response.body = JSON.stringify({ resp: bytesToHex(respBytes) });
      updateVirtualComponentsFromExchange(bytes, respBytes);
    }
    response.send();
  });
}

function bindComponents() {
  var i;

  for (i = 0; i < ENTITIES.length; i++) {
    ENTITIES[i].handle = Virtual.getHandle(ENTITIES[i].vc);
    if (ENTITIES[i].handle === null) {
      print("ERROR: Missing virtual component " + ENTITIES[i].vc);
      return false;
    }
  }
  return true;
}

function start() {
  if (!bindComponents()) return;

  state.uart = UART.get();
  if (state.uart === null) {
    print("ERROR: UART is not available; select js_uart serial mode");
    return;
  }
  if (!state.uart.configure({
    baud: CONFIG.BAUD_RATE,
    mode: CONFIG.MODE
  })) {
    print("ERROR: UART configuration failed");
    return;
  }

  state.uart.recv(onReceive);

  HTTPServer.registerEndpoint(CONFIG.HTTP_ENDPOINT_NAME, handleModbusEndpoint);

  print("Deye HTTP proxy started: 9600 8N1, endpoint /" + CONFIG.HTTP_ENDPOINT_NAME
    + " - virtual components update passively from proxied reads");
}

start();
