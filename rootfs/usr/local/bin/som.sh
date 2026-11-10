#!/bin/bash
# Placa de som virtual: tudo que toca no computador virtual vai para "virtual",
# e o servidor captura de "virtual.monitor" para mandar ao iPad.
mkdir -p "$XDG_RUNTIME_DIR"
exec pulseaudio -n --daemonize=no --exit-idle-time=-1 --disallow-exit --log-target=stderr \
  -L "module-native-protocol-unix" \
  -L "module-null-sink sink_name=virtual sink_properties=device.description=Som-do-iPad" \
  -L "module-always-sink"
