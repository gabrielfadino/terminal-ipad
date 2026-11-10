"""Atualização do Terminal iPad a partir do GitHub.

Fluxo:
  1. verificar(): pergunta ao GitHub qual é o último commit do ramo configurado.
  2. aplicar(): baixa esse commit, confere o código, grava os arquivos na pasta
     do projeto (a mesma pasta do PC, montada no contêiner) e anota a versão.
Arquivos locais como .env, ACESSO.txt e o registro da instalação nunca são tocados.
Mudanças no Dockerfile ou em rootfs/ só valem depois de rodar o instalar.bat no PC;
nesses casos o resultado traz "reconstruir": True.
"""
import hashlib
import io
import os
import shutil
import tarfile

import aiohttp

REPO = os.environ.get("ATUALIZAR_REPO", "gabrielfadino/terminal-ipad").strip()
RAMO = os.environ.get("ATUALIZAR_RAMO", "main").strip()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

API = os.environ.get("ATUALIZAR_API", "https://api.github.com").rstrip("/")
LIMITE_DOWNLOAD = 20 * 1024 * 1024
LIMITE_ARQUIVO = 5 * 1024 * 1024

# nunca sobrescritos pela atualização
PROTEGIDOS = {".env", "ACESSO.txt", "instalar-log.txt", "VERSAO"}
# partes que só valem depois de remontar o contêiner no PC
DA_IMAGEM = ("Dockerfile", "rootfs/")


class ErroAtualizacao(Exception):
    pass


def pasta_projeto():
    """Pasta do projeto montada no contêiner, ou None se não houver."""
    p = os.environ.get("PROJETO_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(os.path.join(p, "docker-compose.yml")):
        return p
    return None


def confirmar_inicio():
    """Chamado quando o servidor está no ar há um tempo: a versão nova deu certo."""
    p = pasta_projeto()
    if p:
        try:
            os.remove(os.path.join(p, ".app-anterior", ".pendente"))
        except OSError:
            pass


def aviso_de_falha():
    """Se a última atualização foi desfeita, devolve a mensagem uma única vez."""
    p = pasta_projeto()
    if not p:
        return ""
    arq = os.path.join(p, ".atualizacao-desfeita")
    try:
        with open(arq, encoding="utf-8") as f:
            sha = f.read().strip()
        os.remove(arq)
    except OSError:
        return ""
    return (f"A versão {sha[:7]} não conseguiu ligar e o sistema voltou sozinho para a anterior. "
            "Nada se perdeu.")


def versao_atual():
    p = pasta_projeto()
    if not p:
        return ""
    try:
        with open(os.path.join(p, "VERSAO"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _cabecalhos():
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "terminal-ipad-atualizador",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    return h


def _erro_http(status):
    if status in (401, 403):
        return "O GitHub recusou o acesso. Confira o GITHUB_TOKEN no arquivo .env."
    if status == 404:
        if TOKEN:
            return f"Não encontrei o repositório {REPO} (ramo {RAMO}). Confira o nome e se o token tem acesso a ele."
        return (f"Não encontrei o repositório {REPO}. Se ele for privado, "
                "coloque um GITHUB_TOKEN (só leitura) no arquivo .env do PC.")
    return f"O GitHub respondeu com erro {status}. Tente de novo em alguns minutos."


async def _ultimo_commit(sessao):
    url = f"{API}/repos/{REPO}/commits/{RAMO}"
    async with sessao.get(url, headers=_cabecalhos()) as r:
        if r.status != 200:
            raise ErroAtualizacao(_erro_http(r.status))
        dados = await r.json()
    commit = dados.get("commit", {})
    mensagem = (commit.get("message") or "").strip().splitlines()
    return {
        "sha": dados.get("sha", ""),
        "mensagem": mensagem[0] if mensagem else "",
        "data": (commit.get("committer") or {}).get("date", ""),
    }


def _sessao():
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))


async def verificar():
    if not pasta_projeto():
        raise ErroAtualizacao("Esta instalação não permite atualizar pelo app. Rode o instalar.bat atualizado no PC.")
    atual = versao_atual()
    try:
        async with _sessao() as s:
            novo = await _ultimo_commit(s)
    except aiohttp.ClientError:
        raise ErroAtualizacao("Sem conexão com o GitHub. Confira a internet do PC.")
    return {
        "atual": atual[:7],
        "nova": novo["sha"][:7],
        "mensagem": novo["mensagem"],
        "data": novo["data"],
        "disponivel": bool(novo["sha"]) and novo["sha"] != atual,
    }


def _caminho_seguro(nome):
    """Tira a pasta raiz do pacote do GitHub e recusa caminhos perigosos."""
    partes = nome.split("/", 1)
    if len(partes) < 2 or not partes[1]:
        return None
    rel = partes[1]
    if rel.startswith("/") or "\\" in rel:
        return None
    pedacos = rel.split("/")
    if any(p in ("", ".", "..") for p in pedacos):
        return None
    if rel in PROTEGIDOS or pedacos[0] == ".git":
        return None
    return rel


def _impressao_imagem(pasta, arquivos=None):
    """Resumo do Dockerfile e de rootfs/, para saber se é preciso remontar."""
    h = hashlib.sha256()
    if arquivos is None:
        arquivos = {}
        for raiz, _, nomes in os.walk(pasta):
            for n in nomes:
                cheio = os.path.join(raiz, n)
                rel = os.path.relpath(cheio, pasta).replace(os.sep, "/")
                if rel == "Dockerfile" or rel.startswith("rootfs/"):
                    with open(cheio, "rb") as f:
                        arquivos[rel] = f.read()
    for rel in sorted(arquivos):
        if rel == "Dockerfile" or rel.startswith("rootfs/"):
            conteudo = arquivos[rel].replace(b"\r\n", b"\n")
            h.update(rel.encode() + b"\0" + hashlib.sha256(conteudo).digest())
    return h.hexdigest()


async def aplicar():
    pasta = pasta_projeto()
    if not pasta:
        raise ErroAtualizacao("Esta instalação não permite atualizar pelo app. Rode o instalar.bat atualizado no PC.")
    try:
        async with _sessao() as s:
            novo = await _ultimo_commit(s)
            url = f"{API}/repos/{REPO}/tarball/{novo['sha']}"
            async with s.get(url, headers=_cabecalhos()) as r:
                if r.status != 200:
                    raise ErroAtualizacao(_erro_http(r.status))
                bruto = bytearray()
                async for bloco in r.content.iter_chunked(65536):
                    bruto.extend(bloco)
                    if len(bruto) > LIMITE_DOWNLOAD:
                        raise ErroAtualizacao("O pacote da atualização é grande demais.")
    except aiohttp.ClientError:
        raise ErroAtualizacao("Sem conexão com o GitHub. Confira a internet do PC.")

    # lê o pacote inteiro na memória antes de gravar qualquer coisa
    arquivos = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(bytes(bruto)), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                rel = _caminho_seguro(m.name)
                if not rel or m.size > LIMITE_ARQUIVO:
                    continue
                arquivos[rel] = tar.extractfile(m).read()
    except tarfile.TarError:
        raise ErroAtualizacao("O pacote baixado do GitHub veio com defeito.")

    servidor = arquivos.get("app/server.py")
    if servidor is None or "docker-compose.yml" not in arquivos:
        raise ErroAtualizacao("O repositório não parece ser o do Terminal iPad. Nada foi alterado.")
    for rel, conteudo in arquivos.items():
        if rel.endswith(".py"):
            try:
                compile(conteudo, rel, "exec")
            except SyntaxError as e:
                raise ErroAtualizacao(f"A nova versão tem um erro em {rel} (linha {e.lineno}). Nada foi alterado.")

    antes = _impressao_imagem(pasta)
    depois = _impressao_imagem(pasta, arquivos)

    # guarda a versão atual do app; se a nova não ligar, o servidor volta para ela
    anterior = os.path.join(pasta, ".app-anterior")
    shutil.rmtree(anterior, ignore_errors=True)
    shutil.copytree(os.path.join(pasta, "app"), anterior,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    open(os.path.join(anterior, ".pendente"), "w").close()
    with open(os.path.join(anterior, ".versao"), "w", encoding="utf-8") as f:
        f.write(versao_atual() + "\n")

    # grava cada arquivo por inteiro e só então troca pelo antigo
    for rel, conteudo in sorted(arquivos.items()):
        destino = os.path.join(pasta, *rel.split("/"))
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        try:
            with open(destino, "rb") as f:
                if f.read() == conteudo:
                    continue
        except OSError:
            pass
        temp = destino + ".novo"
        with open(temp, "wb") as f:
            f.write(conteudo)
        os.replace(temp, destino)

    with open(os.path.join(pasta, "VERSAO"), "w", encoding="utf-8") as f:
        f.write(novo["sha"] + "\n")

    return {
        "ok": True,
        "versao": novo["sha"][:7],
        "mensagem": novo["mensagem"],
        "reconstruir": antes != depois,
    }

