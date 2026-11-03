# Personalização de temas

Em **Configurações → Aparência**, o SFTranslator oferece seis temas base com prévias da interface, gradientes, imagem de fundo PNG/GIF, fontes do sistema, animações, estilo e animação dos ícones, temas oficiais do SFDownloader, CSS visual restrito e importação de temas locais.

As preferências são salvas em `settings.json` no diretório de dados do aplicativo. Configurações antigas recebem os valores padrão. Os estados dos jogos (instalado, pendente, incompatível e não configurado) preservam suas cores próprias.

## Imagens e temas locais

### Temas oficiais

A galeria mostra miniaturas leves incluídas no aplicativo. Ao selecionar um tema, o SFTranslator baixa as imagens principal, média e compacta diretamente de `NskBR/SFDownloader-App/themes/wallpapers` e verifica tamanho, formato e SHA-256 contra o manifesto incluído na versão do aplicativo. As imagens ficam em `official-themes` no diretório de dados e podem ser aplicadas offline. Novos temas ou alterações no manifesto exigem atualização do aplicativo, como no SFDownloader. Excluir um tema remove apenas suas imagens baixadas pelo SFTranslator.

O papel de parede percorre toda a janela. Os painéis usam vidro fosco com `blur(16px) saturate(125%)`, sem borda aparente; os botões da barra lateral têm contorno fino. As cores funcionais de status continuam independentes do tema.

### Temas locais

As imagens importadas ficam armazenadas por hash SHA-256 no diretório de dados do SFTranslator e não precisam de conexão. Limites: 20 MiB por PNG/GIF, dimensão máxima de 8192 px, 32 milhões de pixels para PNG e 8 milhões para GIF.

O importador de ZIP aceita o mesmo `theme.json` de esquema 1 do SFDownloader. Exemplo:

```json
{
  "schemaVersion": 1,
  "name": "Meu tema",
  "author": "Seu nome",
  "variants": [{
    "name": "Original",
    "image": "images/main.png",
    "preview": "images/preview.png",
    "preset": "custom",
    "appearance": {
      "palette": {"surface":"#201d28", "raised":"#342d44", "accent":"#c3a5ed", "strong":"#eadbff"}
    },
    "darkness": 50,
    "panelOpacity": 86,
    "position": "center"
  }]
}
```

Cada ZIP pode ter até 80 MiB, 100 arquivos e 20 variações. Quando disponível, o aplicativo usa `medium` como papel de parede da janela; depois tenta `compact` e `image`. A miniatura usa `preview`. O papel de parede é único para titlebar, sidebar e conteúdo; cartões e controles recebem vidro translúcido com a opacidade definida pelo tema. Os caminhos internos são validados para impedir saída da pasta. Só `theme.json`, PNG e GIF são aceitos.

## CSS personalizado

O editor aceita apenas `.game-card`, `.settings-panel`, `.model-card`, `aside nav button`, `.page-heading h1`, `.sidebar-overview` e `.theme-tile`. As propriedades disponíveis são `color`, `background-color`, `border-color` com cores `#RRGGBB`, além de `border-radius`, `letter-spacing` e `font-size` em pixels. Recursos remotos, `url()`, `@import`, variáveis e posicionamento não são aceitos.

As regras CSS específicas do gerenciador de downloads não são copiadas automaticamente para o tradutor. As miniaturas oficiais incluídas no aplicativo vêm do repositório SFDownloader-App; os papéis de parede completos são baixados sob demanda.
