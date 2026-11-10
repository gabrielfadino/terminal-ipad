#!/bin/bash
# Liga o servidor do Terminal.
# Usa o app da pasta do projeto (atualizável pelo botão Atualizar); se ela não
# estiver montada, usa a cópia que veio dentro da imagem.
# Se uma atualização deixar o servidor sem conseguir ligar, volta para a versão anterior.
PROJ=/opt/projeto
ANTERIOR="$PROJ/.app-anterior"

if [ ! -f "$PROJ/app/server.py" ]; then
  exec /usr/bin/python3 /opt/terminal/server.py
fi

inicio=$(date +%s)
/usr/bin/python3 "$PROJ/app/server.py"
codigo=$?
duracao=$(( $(date +%s) - inicio ))

if [ $codigo -ne 0 ] && [ $duracao -lt 20 ] && [ -f "$ANTERIOR/.pendente" ]; then
  echo "[terminal] a versão nova não ligou; voltando para a anterior"
  rm -f "$ANTERIOR/.pendente"
  cat "$PROJ/VERSAO" > "$PROJ/.atualizacao-desfeita" 2>/dev/null
  if [ -s "$ANTERIOR/.versao" ]; then cp "$ANTERIOR/.versao" "$PROJ/VERSAO"; else rm -f "$PROJ/VERSAO"; fi
  rm -f "$ANTERIOR/.versao"
  cp -a "$ANTERIOR/." "$PROJ/app/"
  mv "$ANTERIOR" "$PROJ/.app-com-defeito-$(date +%Y%m%d%H%M%S)" 2>/dev/null
fi
exit $codigo
