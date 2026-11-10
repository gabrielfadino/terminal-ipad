#!/usr/bin/env python3
"""Terminal iPad — servidor do computador virtual.

Entrega ao iPad 2 (Safari 9):
  - a tela do computador virtual como MJPEG  (/stream.mjpg)
  - o som como MP3 contínuo                  (/m/<token>/audio.mp3)
  - o Modo Cinema como HLS (H.264 + AAC)     (/m/<token>/live.m3u8)
e recebe toques e teclado                     (/api/input).

Configuração por variáveis de ambiente (veja o LEIA-ME).
"""
import asyncio
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import time

from aiohttp import web


def env_int(nome, padrao):
    try:
        return int(os.environ.get(nome, padrao))
    except ValueError:
        return padrao


LARGURA = env_int("LARGURA", 1024)
ALTURA = env_int("ALTURA", 768)
DISPLAY = os.environ.get("DISPLAY", ":1")
SENHA = os.environ.get("SENHA", "")
PORTA = env_int("PORTA", 8090)
OCIOSO = env_int("SESSAO_OCIOSA_MIN", 30) * 60
MAXIMO = env_int("SESSAO_MAX_HORAS", 8) * 3600
FONTE_SOM = os.environ.get("FONTE_SOM", "virtual.monitor")
SAIDA_SOM = os.environ.get("SAIDA_SOM", "virtual")
COOKIE_SEGURO = os.environ.get("COOKIE_SEGURO", "auto")  # auto | sim | nao
HLS_DIR = os.environ.get("HLS_DIR", "/tmp/terminal-hls")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

COOKIE = "tsess"
JANELA_FALHAS = 15 * 60
MAX_FALHAS = 8

NOCACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}

# Qualidade da tela (Modo Trabalho): limites aceitos
FPS_MIN, FPS_MAX = 1, 15
Q_MIN, Q_MAX = 2, 31

# Qualidade do Modo Cinema: (bitrate, maxrate, bufsize, escala)
CINEMA = {
    "baixa": ("800k", "1000k", "2000k", "800:600"),
    "media": ("1500k", "1800k", "3000k", None),
    "alta": ("2500k", "3000k", "5000k", None),
}

BOTOES = {"esq": "1", "meio": "2", "dir": "3"}
TECLA_RE = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")
SEGMENTO_RE = re.compile(r"^s\d{6}\.ts$")


def log(*args):
    print("[terminal]", *args, flush=True)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def int_ou(v, padrao):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return padrao


def agora():
    return time.time()


# ---------------------------------------------------------------- sessões

sessoes = {}   # token -> {"criada", "vista", "midia", "mjpeg"}
midias = {}    # token de mídia -> token de sessão
falhas = []    # horários das tentativas de senha erradas


def nova_sessao():
    tok = secrets.token_urlsafe(32)
    mt = secrets.token_urlsafe(24)
    t = agora()
    sessoes[tok] = {"criada": t, "vista": t, "midia": mt, "mjpeg": None}
    midias[mt] = tok
    return tok


def encerrar(tok):
    s = sessoes.pop(tok, None)
    if s:
        midias.pop(s["midia"], None)
        matar(s.get("mjpeg"))


def valida(tok):
    s = sessoes.get(tok) if tok else None
    if not s:
        return None
    t = agora()
    if t - s["vista"] > OCIOSO or t - s["criada"] > MAXIMO:
        encerrar(tok)
        return None
    return s


def sessao_req(req):
    tok = req.cookies.get(COOKIE)
    return tok, valida(tok)


def sessao_midia(req):
    tok = midias.get(req.match_info.get("mt", ""))
    return tok, valida(tok)


def cookie_seguro(req):
    if COOKIE_SEGURO == "sim":
        return True
    if COOKIE_SEGURO == "nao":
        return False
    if req.headers.get("X-Forwarded-Proto", "").lower() == "https" or req.secure:
        return True
    return req.host.split(":")[0].endswith(".ts.net")


def redirecionar(local):
    return web.Response(status=303, headers=dict(NOCACHE, Location=local))


def nao_autorizado():
    return web.json_response({"erro": "sessao"}, status=401, headers=NOCACHE)


def origem_ok(req):
    """Bloqueia chamadas vindas de outros sites (CSRF)."""
    origem = req.headers.get("Origin")
    if origem and origem.split("://", 1)[-1] != req.host:
        return False
    return req.content_type == "application/json"


# ---------------------------------------------------------------- processos

def matar(proc):
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def rodar(*cmd):
    try:
        p = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        if p.returncode != 0 and err:
            log("falhou:", cmd[0], err.decode(errors="replace").strip()[:200])
        return p.returncode
    except FileNotFoundError:
        log("programa não encontrado:", cmd[0])
        return -1


async def transmitir(req, resp, cmd, tok, ao_iniciar=None):
    """Roda o ffmpeg e repassa a saída dele para o navegador."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    if ao_iniciar:
        ao_iniciar(proc)
    await resp.prepare(req)
    ultima = agora()
    try:
        while True:
            bloco = await proc.stdout.read(65536)
            if not bloco:
                break
            await resp.write(bloco)
            if agora() - ultima > 15:
                ultima = agora()
                if not valida(tok):
                    break
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        matar(proc)
        try:
            await proc.wait()
        except Exception:
            pass
    return resp


# ---------------------------------------------------------------- Modo Cinema (HLS)

class Cinema:
    def __init__(self):
        self.proc = None
        self.qualidade = "media"
        self.ultimo_pedido = 0.0
        self.trava = asyncio.Lock()

    @property
    def playlist(self):
        return os.path.join(HLS_DIR, "live.m3u8")

    def rodando(self):
        return self.proc is not None and self.proc.returncode is None

    def pronto(self):
        if not self.rodando():
            return False
        try:
            with open(self.playlist, encoding="utf-8") as f:
                return sum(1 for linha in f if linha.strip().endswith(".ts")) >= 3
        except OSError:
            return False

    async def garantir(self, qualidade):
        async with self.trava:
            if self.rodando() and qualidade == self.qualidade:
                return
            await self._parar()
            shutil.rmtree(HLS_DIR, ignore_errors=True)
            os.makedirs(HLS_DIR, exist_ok=True)
            self.qualidade = qualidade
            bv, maxr, buf, escala = CINEMA[qualidade]
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-thread_queue_size", "512",
                "-f", "x11grab", "-draw_mouse", "0", "-framerate", "25",
                "-video_size", f"{LARGURA}x{ALTURA}", "-i", DISPLAY,
                "-thread_queue_size", "512",
                "-f", "pulse", "-i", FONTE_SOM,
            ]
            if escala:
                cmd += ["-vf", f"scale={escala}"]
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-profile:v", "main", "-level", "3.1", "-pix_fmt", "yuv420p",
                "-b:v", bv, "-maxrate", maxr, "-bufsize", buf,
                "-g", "50", "-keyint_min", "50", "-sc_threshold", "0",
                "-af", "aresample=async=1000",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
                # versão 3 do HLS: a que o iOS 9 entende melhor
                "-hls_flags", "delete_segments",
                "-hls_segment_filename", os.path.join(HLS_DIR, "s%06d.ts"),
                self.playlist,
            ]
            self.proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            self.ultimo_pedido = agora()
            log("Modo Cinema ligado, qualidade", qualidade)

    async def _parar(self):
        if self.rodando():
            matar(self.proc)
            await self.proc.wait()
            log("Modo Cinema desligado")
        self.proc = None

    async def parar(self):
        async with self.trava:
            await self._parar()

    async def vigiar(self):
        """Desliga o Modo Cinema se ninguém estiver assistindo."""
        while True:
            await asyncio.sleep(5)
            if self.rodando() and agora() - self.ultimo_pedido > 30:
                await self.parar()


cinema = Cinema()
trava_input = asyncio.Lock()


# ---------------------------------------------------------------- páginas

def arquivo(nome, tipo=None):
    headers = dict(NOCACHE)
    if tipo:
        headers["Content-Type"] = tipo
    return web.FileResponse(os.path.join(STATIC, nome), headers=headers)


async def raiz(req):
    _, s = sessao_req(req)
    if not s:
        return redirecionar("/login")
    return arquivo("app.html")


async def login_get(req):
    _, s = sessao_req(req)
    if s:
        return redirecionar("/")
    return arquivo("login.html")


async def login_post(req):
    t = agora()
    falhas[:] = [f for f in falhas if t - f < JANELA_FALHAS]
    if len(falhas) >= MAX_FALHAS:
        return redirecionar("/login?bloqueado=1")
    dados = await req.post()
    senha = str(dados.get("senha", ""))
    if not hmac.compare_digest(senha.encode("utf-8"), SENHA.encode("utf-8")):
        falhas.append(t)
        log("senha errada")
        await asyncio.sleep(1.0)
        return redirecionar("/login?erro=1")
    tok = nova_sessao()
    resp = redirecionar("/")
    resp.set_cookie(COOKIE, tok, max_age=MAXIMO, httponly=True,
                    secure=cookie_seguro(req), path="/", samesite="Lax")
    log("nova sessão")
    return resp


async def sair(req):
    tok, _ = sessao_req(req)
    encerrar(tok)
    resp = redirecionar("/login")
    resp.del_cookie(COOKIE, path="/")
    return resp


async def icone(req):
    return arquivo("icone.png")


async def saude(req):
    return web.Response(text="ok")


# ---------------------------------------------------------------- tela, som e cinema

async def stream_mjpeg(req):
    tok, s = sessao_req(req)
    if not s:
        return web.Response(status=401, headers=NOCACHE)
    fps = clamp(int_ou(req.query.get("fps"), 10), FPS_MIN, FPS_MAX)
    q = clamp(int_ou(req.query.get("q"), 9), Q_MIN, Q_MAX)
    matar(s.get("mjpeg"))  # só uma tela por sessão
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(fps),
        "-video_size", f"{LARGURA}x{ALTURA}", "-i", DISPLAY,
        # descarta quadros repetidos (tela parada = quase nada de internet),
        # mas manda pelo menos um por segundo
        "-vf", f"mpdecimate=max={fps}:hi=768:lo=320:frac=0.33",
        "-fps_mode", "vfr",
        "-c:v", "mjpeg", "-q:v", str(q),
        "-flush_packets", "1",  # entrega cada quadro na hora, sem acumular
        "-f", "mpjpeg", "-boundary_tag", "quadro", "-",
    ]
    resp = web.StreamResponse(headers=dict(
        NOCACHE, **{"Content-Type": "multipart/x-mixed-replace; boundary=quadro",
                    "X-Accel-Buffering": "no"}))

    def guardar(proc):
        s["mjpeg"] = proc

    return await transmitir(req, resp, cmd, tok, guardar)


async def audio_mp3(req):
    tok, s = sessao_midia(req)
    if not s:
        return web.Response(status=401, headers=NOCACHE)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer",
        "-f", "pulse", "-i", FONTE_SOM,
        "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k",
        "-flush_packets", "1", "-f", "mp3", "-",
    ]
    resp = web.StreamResponse(headers=dict(
        NOCACHE, **{"Content-Type": "audio/mpeg", "Accept-Ranges": "none"}))
    return await transmitir(req, resp, cmd, tok)


async def hls_playlist(req):
    _, s = sessao_midia(req)
    if not s:
        return web.Response(status=401, headers=NOCACHE)
    s["vista"] = agora()  # assistir conta como uso
    qualidade = req.query.get("q", cinema.qualidade)
    if qualidade not in CINEMA:
        qualidade = "media"
    await cinema.garantir(qualidade)
    cinema.ultimo_pedido = agora()
    for _ in range(100):  # espera até 25 s pelo começo do vídeo
        if cinema.pronto():
            break
        await asyncio.sleep(0.25)
    else:
        return web.Response(status=503, text="video ainda nao pronto", headers=NOCACHE)
    with open(cinema.playlist, encoding="utf-8") as f:
        texto = f.read()
    return web.Response(text=texto, content_type="application/vnd.apple.mpegurl", headers=NOCACHE)


async def hls_segmento(req):
    _, s = sessao_midia(req)
    if not s:
        return web.Response(status=401, headers=NOCACHE)
    nome = req.match_info["nome"]
    caminho = os.path.join(HLS_DIR, nome)
    if not SEGMENTO_RE.match(nome) or not os.path.isfile(caminho):
        return web.Response(status=404, headers=NOCACHE)
    cinema.ultimo_pedido = agora()
    return web.FileResponse(caminho, headers={"Content-Type": "video/mp2t", "Cache-Control": "no-cache"})


# ---------------------------------------------------------------- API

async def api_estado(req):
    _, s = sessao_req(req)
    if not s:
        return nao_autorizado()
    return web.json_response({
        "largura": LARGURA, "altura": ALTURA, "midia": s["midia"],
        "cinema": cinema.rodando(),
        "ociosoMin": OCIOSO // 60,
    }, headers=NOCACHE)


async def api_input(req):
    _, s = sessao_req(req)
    if not s:
        return nao_autorizado()
    if not origem_ok(req):
        return web.json_response({"erro": "origem"}, status=403)
    try:
        dados = await req.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"erro": "json"}, status=400)
    if isinstance(dados, dict):
        dados = [dados]
    if not isinstance(dados, list):
        return web.json_response({"erro": "formato"}, status=400)
    s["vista"] = agora()

    comandos = []
    mouse = []

    def descarregar():
        if mouse:
            comandos.append(["xdotool"] + mouse[:])
            del mouse[:]

    for ev in dados[:300]:
        if not isinstance(ev, dict):
            continue
        t = ev.get("t")
        x = str(clamp(int_ou(ev.get("x"), 0), 0, LARGURA - 1))
        y = str(clamp(int_ou(ev.get("y"), 0), 0, ALTURA - 1))
        b = BOTOES.get(ev.get("b"), "1")
        if t == "mover":
            mouse += ["mousemove", x, y]
        elif t == "clique":
            mouse += ["mousemove", x, y, "click", b]
        elif t == "duplo":
            mouse += ["mousemove", x, y, "click", "--repeat", "2", "--delay", "60", b]
        elif t == "baixo":
            mouse += ["mousemove", x, y, "mousedown", b]
        elif t == "cima":
            mouse += ["mousemove", x, y, "mouseup", b]
        elif t in ("rolar", "rolar_h"):
            n = clamp(int_ou(ev.get("n"), 0), -25, 25)
            if n:
                if t == "rolar":
                    botao = "5" if n > 0 else "4"
                else:
                    botao = "7" if n > 0 else "6"
                mouse += ["mousemove", x, y, "click", "--repeat", str(abs(n)), "--delay", "12", botao]
        elif t == "texto":
            descarregar()
            texto = str(ev.get("s", ""))[:2000]
            if texto:
                comandos.append(["xdotool", "type", "--clearmodifiers", "--delay", "6", "--", texto])
        elif t == "tecla":
            descarregar()
            k = str(ev.get("k", ""))
            if len(k) <= 40 and TECLA_RE.match(k):
                comandos.append(["xdotool", "key", "--clearmodifiers", k])
    descarregar()

    async with trava_input:
        for c in comandos:
            await rodar(*c)
    return web.json_response({"ok": True}, headers=NOCACHE)


async def api_cinema(req):
    _, s = sessao_req(req)
    if not s:
        return nao_autorizado()
    if not origem_ok(req):
        return web.json_response({"erro": "origem"}, status=403)
    dados = await req.json()
    if dados.get("acao") == "parar":
        await cinema.parar()
    return web.json_response({"cinema": cinema.rodando()}, headers=NOCACHE)


async def api_volume(req):
    _, s = sessao_req(req)
    if not s:
        return nao_autorizado()
    if not origem_ok(req):
        return web.json_response({"erro": "origem"}, status=403)
    dados = await req.json()
    acao = dados.get("acao")
    s["vista"] = agora()
    if acao == "mais":
        await rodar("pactl", "set-sink-volume", SAIDA_SOM, "+8%")
    elif acao == "menos":
        await rodar("pactl", "set-sink-volume", SAIDA_SOM, "-8%")
    elif acao == "mudo":
        await rodar("pactl", "set-sink-mute", SAIDA_SOM, "toggle")
    return web.json_response({"ok": True}, headers=NOCACHE)


# ---------------------------------------------------------------- app

@web.middleware
async def cabecalhos(req, handler):
    resp = await handler(req)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


async def ao_iniciar(app):
    app["vigia"] = asyncio.ensure_future(cinema.vigiar())


async def ao_encerrar(app):
    app["vigia"].cancel()
    await cinema.parar()
    for tok in list(sessoes):
        encerrar(tok)


def criar_app():
    app = web.Application(middlewares=[cabecalhos], client_max_size=256 * 1024)
    app.router.add_get("/", raiz)
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login_post)
    app.router.add_get("/sair", sair)
    app.router.add_get("/icone.png", icone)
    app.router.add_get("/saude", saude)
    app.router.add_get("/stream.mjpg", stream_mjpeg)
    app.router.add_get("/m/{mt}/audio.mp3", audio_mp3)
    app.router.add_get("/m/{mt}/live.m3u8", hls_playlist)
    app.router.add_get("/m/{mt}/{nome}", hls_segmento)
    app.router.add_get("/api/estado", api_estado)
    app.router.add_post("/api/input", api_input)
    app.router.add_post("/api/cinema", api_cinema)
    app.router.add_post("/api/volume", api_volume)
    app.on_startup.append(ao_iniciar)
    app.on_cleanup.append(ao_encerrar)
    return app


def main():
    if len(SENHA) < 8:
        log("ERRO: defina a variável SENHA com pelo menos 8 caracteres (arquivo .env).")
        sys.exit(1)
    log(f"tela {LARGURA}x{ALTURA} em {DISPLAY}, porta {PORTA}")
    web.run_app(criar_app(), host="0.0.0.0", port=PORTA, access_log=None, print=None)


if __name__ == "__main__":
    main()
