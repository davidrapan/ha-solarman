## Inverter definitions example

default:
  update_interval: 10                       ## Default update interval. Can also be used on groups and items
  digits: 6                                 

parameters:
  - group: Passive settings                 ## Name of the group
    items:
      - name: "Passive: Desired Grid Power" ## Item name
        platform: number                    ## Item value format
        class: "power"                      
        state_class: "measurement"
        uom: "W"
        rule: 2                             ## Value format. See parser.py function try_parse_field. rule: 2 means unsigned int
        registers: [0x1188, 0x1187]         ## Registers of the value. Depending on inverter might be big or little endian
        range:                              ## value range
          min: -2147483648 
          max: 2147483647
