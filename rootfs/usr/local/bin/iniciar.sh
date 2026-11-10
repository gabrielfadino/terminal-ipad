#!/bin/bash
set -e

if [ "${#SENHA}" -lt 8 ]; then
  echo "ERRO: defina SENHA (pelo menos 8 caracteres) no arquivo .env antes de ligar o Terminal."
  exit 1
fi

# pasta de execução do usuário (som e sessão)
mkdir -p /run/user/1000
chown terminal:terminal /run/user/1000
chmod 700 /run/user/1000

# a pasta pessoal fica num volume; garante o dono certo
chown terminal:terminal /home/terminal

# o botão "Atualizar sistema" precisa gravar na pasta do projeto
if [ -d /opt/projeto ] && ! su terminal -s /bin/sh -c 'test -w /opt/projeto -a -w /opt/projeto/app'; then
  chown -R terminal:terminal /opt/projeto 2>/dev/null || true
fi

# limpa travas de uma execução anterior
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
mkdir -p /tmp/.X11-unix /tmp/.ICE-unix
chmod 1777 /tmp/.X11-unix /tmp/.ICE-unix

exec /usr/bin/supervisord -n -c /etc/supervisor/terminal.conf
