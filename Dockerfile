# Terminal iPad — computador virtual para usar no iPad 2 pelo navegador
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=pt_BR.UTF-8 LANGUAGE=pt_BR:pt LC_ALL=pt_BR.UTF-8 \
    TZ=America/Sao_Paulo \
    DISPLAY=:1 LARGURA=1024 ALTURA=768 PORTA=8090

# Área de trabalho leve, tela e som virtuais, conversor de vídeo e servidor
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb xauth xdotool x11-xserver-utils dbus-x11 at-spi2-core \
      xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings xfce4-terminal \
      thunar mousepad adwaita-icon-theme \
      pulseaudio pulseaudio-utils \
      ffmpeg \
      python3 python3-aiohttp \
      supervisor tini locales tzdata ca-certificates curl \
      fonts-noto-core fonts-noto-color-emoji fonts-liberation \
 && locale-gen pt_BR.UTF-8 \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && (userdel -r ubuntu 2>/dev/null || true) \
 && useradd -m -s /bin/bash -u 1000 terminal \
 && rm -rf /var/lib/apt/lists/*

# Navegador: Firefox oficial da Mozilla (o do Ubuntu é "snap" e não roda em contêiner)
ARG NAVEGADOR=firefox
RUN if [ "$NAVEGADOR" = "firefox" ]; then \
      install -d -m 0755 /etc/apt/keyrings \
   && curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg -o /etc/apt/keyrings/packages.mozilla.org.asc \
   && echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" > /etc/apt/sources.list.d/mozilla.list \
   && printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' > /etc/apt/preferences.d/mozilla \
   && apt-get update && apt-get install -y --no-install-recommends firefox firefox-l10n-pt-br \
   && rm -rf /var/lib/apt/lists/* ; \
    else \
      apt-get update && apt-get install -y --no-install-recommends xterm && rm -rf /var/lib/apt/lists/* ; \
    fi

COPY rootfs/ /
COPY app/ /opt/terminal/
RUN chmod +x /usr/local/bin/*.sh

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fs http://127.0.0.1:8090/saude || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/iniciar.sh"]
