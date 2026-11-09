# Gwiro

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

Na primeira execução o Gwiro cria `data/config.json`. Se quiser partir do modelo, copie `data/config.example.json` para `data/config.json` antes de abrir o painel.

## Como usar

1. Em **Grupos**, crie ou abra o grupo. Cada grupo tem as próprias vitrines, nichos, canais e tempos.
2. Em **Nichos**, ligue os temas que interessam. Cada um tem palavras-chave, desconto mínimo, faixa de preço e as lojas em que a busca entra. Sem nicho ativo, o bot usa as palavras gravadas em cada vitrine.
3. Em **Vitrines**, ligue as lojas e informe a etiqueta de afiliado e as chaves de API.
4. Em **Canais**, escolha Telegram, WhatsApp ou os dois e grave os tokens.
5. Em **Tempos**, defina a pausa entre mensagens, o teto por ciclo e o horário silencioso.
6. Em **Mensagem**, edite o texto. A prévia usa uma oferta de exemplo. `{niche}` entra o nome do nicho.
7. Clique em **Iniciar**. **Buscar** só coleta. **Testar envio** manda uma oferta fictícia. **Oferta manual** monta um anúncio no grupo aberto.

A mesma oferta não é reenviada dentro da janela configurada em horas.

## Credenciais

Preencha estes dados no painel. Eles ficam em `data/config.json`, que não entra no Git.

- **Mercado Livre:** a busca abre a vitrine no Chrome, porque a API pública responde 403. A etiqueta é a do Linkbuilder e vira o link curto quando a sessão do afiliado existe.
- **Amazon:** Product Advertising API. Access key, secret key e partner tag.
- **Shopee:** Open API de afiliados do Brasil (`App ID` e `Secret`).
- **AliExpress:** `aliexpress.affiliate.product.query`, com app key, app secret e tracking ID.
- **Telegram:** token do @BotFather e o chat ID do grupo, canal ou conversa.
- **WhatsApp:** Cloud API da Meta. O texto livre vale dentro da janela de 24 horas. Fora dela, cadastre um template com quatro variáveis, nesta ordem: título, preço, desconto e link.

O painel só mostra os quatro últimos caracteres de um segredo já salvo. Deixar o campo em branco na hora de salvar mantém o valor anterior.

A senha do painel, se for preenchida, passa a ser exigida no próximo acesso.

Ofertas, registro, estado da busca e o perfil do Chrome (`data/ml_profile`) também ficam só nesta máquina.
