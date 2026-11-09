# Ogwiro

Bot local que busca promoções na Amazon, no Mercado Livre, na Shopee e no AliExpress e envia para Telegram, WhatsApp ou os dois. Tudo é ajustado no painel.

## Abrir

É preciso ter Python 3.11 ou mais novo. Não há pacotes para instalar.

```bat
run.bat
```

Ou:

```bash
python server.py
```

O painel abre em [http://127.0.0.1:8787](http://127.0.0.1:8787). Ele escuta só neste computador.

## Como usar

1. Em **Nichos**, ligue os temas que interessam. Cada um tem palavras-chave, desconto mínimo, faixa de preço e as lojas em que a busca entra. Sem nicho ativo, o bot usa as palavras gravadas em cada loja.
2. Em **Lojas**, ligue as vitrines, informe o intervalo e os tokens de afiliado.
3. Em **Canais**, escolha Telegram, WhatsApp ou os dois e grave os tokens.
4. Em **Tempos**, defina a pausa entre mensagens, o teto por ciclo e o horário silencioso.
5. Em **Mensagem**, edite o texto. A prévia usa uma oferta de exemplo. `{niche}` entra o nome do nicho.
6. Clique em **Iniciar**. **Buscar** só coleta. **Testar envio** manda uma oferta fictícia.

A mesma oferta não é reenviada dentro da janela configurada em horas.

## Credenciais

- **Mercado Livre:** a busca abre a vitrine no Chrome, porque a API pública responde 403. `matt_tool` é a etiqueta do Linkbuilder e vira o link curto quando a sessão do afiliado existe.
- **Amazon:** Product Advertising API. Access key, secret key e partner tag.
- **Shopee:** Open API de afiliados do Brasil (`App ID` e `Secret`).
- **AliExpress:** `aliexpress.affiliate.product.query`, com app key, app secret e tracking ID.
- **Telegram:** token do @BotFather e o chat ID do grupo, canal ou conversa.
- **WhatsApp:** Cloud API da Meta. O texto livre vale dentro da janela de 24 horas. Fora dela, cadastre um template com quatro variáveis, nesta ordem: título, preço, desconto e link.

Os segredos ficam em `data/config.json` e o painel só mostra os quatro últimos caracteres. Deixar o campo em branco na hora de salvar mantém o valor anterior.

A senha do painel, se for preenchida, passa a ser exigida no próximo acesso.
