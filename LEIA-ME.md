# Terminal iPad

Um computador virtual que roda isolado dentro do seu PC Windows e aparece na tela do iPad 2.
O iPad vira a tela, o toque e o teclado; o processamento todo fica no PC.

- **Modo Trabalho:** tela ao vivo com resposta rápida, para navegar, ler e editar.
- **Modo Cinema:** vídeo fluido com som, para assistir. A resposta tem alguns segundos de atraso.
- O computador virtual tem tela, som e navegador próprios. Você continua usando o Windows normalmente.

---

## Jeito rápido

Extraia o zip e dê dois cliques em **instalar.bat**. Ele instala o Docker Desktop se faltar,
cria uma senha forte, monta o computador virtual, liga o Funnel e mostra o endereço e a senha
(também salvos no arquivo `ACESSO.txt`). Se ele pedir para reiniciar o PC, reinicie e rode de novo.

Os passos abaixo explicam o que o instalador faz, caso prefira fazer à mão.

## 1. O que você precisa

- PC com Windows 10 ou 11, com 8 GB de RAM ou mais (16 GB é o ideal)
- Docker Desktop
- Tailscale instalado e conectado nesse PC (o mesmo que você já usa)
- iPad 2 com iOS 9.3.5 e internet

## 2. Instalar o Docker Desktop

1. Baixe em https://www.docker.com/products/docker-desktop e instale com as opções padrão (usa o WSL 2).
2. Reinicie o PC se ele pedir.
3. Abra o Docker Desktop e, em **Settings > General**, marque **Start Docker Desktop when you sign in**.
   Assim o Terminal liga sozinho junto com o Windows.

## 3. Preparar a pasta

1. Extraia o arquivo `terminal-ipad.zip` em `C:\terminal-ipad`.
2. Nessa pasta, copie o arquivo `.env.example` e renomeie a cópia para `.env`.
3. Abra o `.env` no Bloco de Notas e troque `SENHA=troque-esta-senha` por uma senha forte,
   com pelo menos 12 caracteres. É ela que protege o acesso pela internet.

## 4. Ligar o Terminal

Abra o PowerShell e rode:

```powershell
cd C:\terminal-ipad
docker compose up -d --build
```

A primeira vez demora de 10 a 20 minutos, porque ele baixa e monta o computador virtual.
Nas próximas, liga em segundos.

Para conferir, abra `http://localhost:8090` no navegador do PC e entre com a senha.
Você deve ver a área de trabalho com o Firefox aberto.

## 5. Publicar pelo Funnel do Tailscale

No PowerShell:

```powershell
tailscale funnel --bg 8090
tailscale funnel status
```

O segundo comando mostra o endereço, algo como `https://nome-do-pc.tailXXXX.ts.net`.

Se aparecer erro de permissão, libere o Funnel para este computador no painel do Tailscale
(**Access controls**, atributo `funnel`), do mesmo jeito que foi feito para o Doca.

Para tirar o Terminal da internet a qualquer momento:

```powershell
tailscale funnel reset
```

## 6. Preparar o iPad 2 (uma vez só)

O iOS 9 não conhece a autoridade que assina os certificados do Funnel. Basta instalá-la:

1. No Safari do iPad, abra `http://x1.i.lencr.org/` e toque em **Instalar** quando aparecer o perfil.
2. Repita com `http://x2.i.lencr.org/`.
3. Os perfis aparecem em **Ajustes > Geral > Perfis**.

Depois:

1. Abra o endereço do Funnel no Safari e entre com a senha.
2. Toque em **Compartilhar > Adicionar à Tela de Início**. O Terminal passa a abrir em tela cheia, como um app.
3. Em **Ajustes > Geral > Bloqueio Automático**, escolha um tempo maior enquanto estiver usando.

## 7. Como usar

| Gesto | Ação |
|---|---|
| Toque | Clique |
| Arrastar um dedo | Rolar a página |
| Segurar | Botão direito |
| Segurar e arrastar | Selecionar texto ou mover janelas |
| Toque com dois dedos | Botão direito |
| Dois toques rápidos | Clique duplo |

O botão **☰** no canto abre o menu:

- **Teclado:** abre o teclado do iPad e uma barra com Esc, Tab, Ctrl, Alt e setas.
  Para atalhos, toque em Ctrl e depois na letra (Ctrl + C, por exemplo).
- **Modo Cinema:** vídeo fluido com som. Toque na tela para mostrar o controle remoto
  (play/pausa, avançar, volume, tela cheia). Os comandos aparecem com alguns segundos de atraso.
- **Som:** liga o som no Modo Trabalho.
- **Qualidade:** automática (padrão: ajusta sozinha à velocidade da conexão), baixa, média ou alta.

Para assistir uma série: abra o site no Firefox pelo Modo Trabalho, dê play,
coloque o vídeo em tela cheia e então entre no Modo Cinema.

## 8. Atualizar pelo próprio sistema

No menu **☰ › Atualizar sistema**, o Terminal confere no GitHub se existe uma versão nova
(repositório definido em `ATUALIZAR_REPO` no `.env`). Se existir, mostra o que mudou e,
com um toque em **Atualizar agora**, baixa, instala e reinicia sozinho em poucos segundos,
sem perder a sessão.

- Se a versão nova não conseguir ligar, o sistema volta sozinho para a anterior e avisa na tela.
- Arquivos do PC como `.env` e `ACESSO.txt` nunca são alterados.
- Quando a mudança mexe na estrutura do computador virtual (`Dockerfile` ou `rootfs/`),
  o aviso pede para rodar o `instalar.bat` no PC para completar.
- **Repositório privado:** crie um token só de leitura no GitHub
  (Settings › Developer settings › Fine-grained tokens, permissão *Contents: Read-only*
  apenas neste repositório) e cole em `GITHUB_TOKEN=` no `.env`. Depois rode o `instalar.bat`.

## 9. Manutenção

```powershell
cd C:\terminal-ipad
docker compose stop          # desliga
docker compose start         # liga de novo
docker compose logs -f       # mostra o que está acontecendo
docker compose up -d --build # aplica uma atualização
```

Os favoritos, senhas e logins do Firefox ficam guardados num volume e sobrevivem às atualizações.

## 10. Segurança

- Pela internet, a única porta aberta é a do Funnel. A porta 8090 do PC só aceita conexões do próprio PC.
- Depois de 8 senhas erradas, o login fica bloqueado por 15 minutos.
- A sessão cai depois de 30 minutos sem uso e, de qualquer forma, 8 horas depois da entrada.
  Os dois tempos podem ser mudados no `.env`.
- Quem entra no Terminal acessa só o computador virtual, nunca os arquivos do Windows.
- Não salve no Firefox do Terminal senhas dos sistemas da empresa.

## 11. Problemas comuns

- **Tela preta no iPad:** toque em ☰ › Recarregar tela. Se continuar, rode `docker compose logs -f` no PC.
- **Erro de certificado no iPad:** confira o passo 6.
- **Modo Cinema não começa:** espere uns 10 segundos e toque em "Reconectar vídeo".
- **Lento ou travando:** baixe a qualidade no menu. O Modo Cinema precisa de uns 3 Mbps de upload no PC.
- **Netflix, Prime e similares:** podem recusar tocar ou mostrar vídeo preto, porque protegem o conteúdo.
  O Terminal não foi feito para contornar essas proteções. Confira também se os termos do seu plano
  permitem o uso nesse aparelho.
