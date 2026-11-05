/**
 * @title Generic Modbus-RTU-over-HTTP Proxy
 * @description Exposes a Shelly's Modbus add-on (UART/RS485) as an HTTP
 * endpoint, so ha-solarman's `shelly_modbus` transport can talk to an
 * inverter directly over the Shelly instead of a WiFi datalogger dongle.
 * Register/brand-agnostic: relays whatever request frame it is given, so
 * it works with any of ha-solarman's supported inverter_definitions.
 *
 * Setup:
 *   1. Install this script on the Shelly and start it.
 *   2. In ha-solarman, set Host = the Shelly's IP, Port = this script's id
 *      (as shown in the Shelly's script list), Transport = "Shelly Modbus
 *      proxy".
 *
 * Contract:
 *   POST http://<shelly-ip>/script/<id>/modbus
 *   Body: hex-encoded Modbus RTU request, CRC16 included (e.g. "010300AF0001B58C")
 *   Response 200: {"resp": "<hex-encoded raw RTU response, CRC16 included>"}
 *   Response 429: {"error": "busy"}     - a transaction is already in flight
 *   Response 504: {"error": "timeout"}  - no response from the bus
 *   Response 400: {"error": "bad_request"}
 *
 * See deye_virtual_components.js for an example of layering local,
 * dashboard-friendly virtual components on top of this same proxy with no
 * extra UART traffic, by snooping on the requests ha-solarman already
 * makes.
 */

var CONFIG = {
  BAUD_RATE: 9600,
  MODE: "8N1",
  RESPONSE_TIMEOUT: 1000,
  ENDPOINT_NAME: "modbus"
};

var state = {
  uart: null,
  rx: [],
  pending: null,
  responseTimer: null
};

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

function bytesToString(bytes) {
  var value = "";
  var i;

  for (i = 0; i < bytes.length; i++) {
    value += String.fromCharCode(bytes[i] & 0xFF);
  }
  return value;
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

// Modbus RTU has no explicit length prefix; a fixed silence window after
// the last received byte marks end-of-frame.
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

function sendRequest(bytes, callback) {
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

  sendRequest(bytes, function (error, respBytes) {
    response.headers = [["Content-Type", "application/json"]];
    if (error !== null) {
      response.code = error === "busy" ? 429 : 504;
      response.body = JSON.stringify({ error: error });
    } else {
      response.code = 200;
      response.body = JSON.stringify({ resp: bytesToHex(respBytes) });
    }
    response.send();
  });
}

function start() {
  state.uart = UART.get();
  if (state.uart === null) {
    print("ERROR: UART is not available; select js_uart serial mode");
    return;
  }
  if (!state.uart.configure({ baud: CONFIG.BAUD_RATE, mode: CONFIG.MODE })) {
    print("ERROR: UART configuration failed");
    return;
  }
  state.uart.recv(onReceive);

  HTTPServer.registerEndpoint(CONFIG.ENDPOINT_NAME, handleModbusEndpoint);
  print("Modbus HTTP proxy started: 9600 8N1, endpoint /" + CONFIG.ENDPOINT_NAME);
}

start();
