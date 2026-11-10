#!/bin/bash
# Inicia a área de trabalho (XFCE) do computador virtual.

# espera a tela virtual ficar pronta
for i in $(seq 1 100); do
  xset q >/dev/null 2>&1 && break
  sleep 0.2
done
xset s off 2>/dev/null
xset s noblank 2>/dev/null

CONF="$HOME/.config"

# painel padrão do XFCE (evita a pergunta de configuração na primeira vez)
PAINEL="$CONF/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
if [ ! -f "$PAINEL" ] && [ -f /etc/xdg/xfce4/panel/default.xml ]; then
  mkdir -p "$(dirname "$PAINEL")"
  cp /etc/xdg/xfce4/panel/default.xml "$PAINEL"
fi

# sem efeitos visuais: deixa a tela mais leve para transmitir
XFWM="$CONF/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
if [ ! -f "$XFWM" ]; then
  mkdir -p "$(dirname "$XFWM")"
  cat > "$XFWM" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="theme" type="string" value="Default-xhdpi"/>
  </property>
</channel>
EOF
fi

# abre o navegador quando a área de trabalho liga
AUTO="$CONF/autostart/navegador.desktop"
if [ ! -f "$AUTO" ]; then
  mkdir -p "$(dirname "$AUTO")"
  if command -v firefox >/dev/null 2>&1; then NAV=firefox; else NAV=xterm; fi
  cat > "$AUTO" <<EOF
[Desktop Entry]
Type=Application
Name=Navegador
Exec=$NAV
X-GNOME-Autostart-enabled=true
EOF
fi

exec dbus-launch --exit-with-session startxfce4
