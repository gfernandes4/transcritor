# Avaliação da interface web pelas 10 heurísticas de Nielsen

Heurísticas: [Nielsen Norman Group, 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).
Avaliação feita em 23/10/2026 sobre a primeira versão (`pagina.html` de uma só tela com quatro blocos empilhados) e o que mudou na segunda.

| # | Heurística | Problema na v1 | O que mudou na v2 |
|---|---|---|---|
| 1 | Visibilidade do estado do sistema | A fila mostrava só "transcrevendo (1/3)" em texto, sem barra e sem dizer qual arquivo. Busca e envio não davam sinal de carregamento. Se o servidor caía, a tela ficava parada sem avisar. | Barra de progresso por envio, nome do arquivo em andamento, progresso do upload em %, estado "Buscando…", aviso fixo quando o servidor local não responde. A fila atualiza mais rápido enquanto há trabalho e mais devagar quando não há. |
| 2 | Correspondência com o mundo real | "Formatos: txt,md,json" e "Envio a1b2c3d4" eram jargão. | Formatos viram opções com nome e descrição ("Legenda SRT"). Cada envio mostra hora e quantidade de áudios, e o identificador sai da vista. |
| 3 | Controle e liberdade | Não dava para tirar um arquivo da seleção, cancelar um envio nem remover um termo do glossário. | Remover arquivo da seleção, cancelar envio (com confirmação em dois passos), remover termo com "Desfazer". Um envio cancelado no meio mantém o que já ficou pronto. |
| 4 | Consistência e padrões | O link "Baixar .zip" parecia texto, os botões variavam, e Enter funcionava só na busca. | Um conjunto de botões (principal, secundário, perigoso), Enter funciona em todos os campos, Ctrl+Enter envia. |
| 5 | Prevenção de erros | Formatos digitados à mão: um erro de digitação só era detectado depois do upload. Tipo de arquivo só checado no servidor. | Formatos por caixas de seleção, JSON sempre ligado (a busca usa), tipo de arquivo checado antes de enviar, botão mostra a contagem real. |
| 6 | Reconhecer em vez de lembrar | Era preciso baixar o .zip para ver o resultado. A identificação de voz não aparecia. | Prévia do texto de cada áudio na própria tela, com falante e número de alertas. Opção "Identificar quem fala" com as pessoas cadastradas listadas. Filtro de falante na busca. |
| 7 | Flexibilidade e eficiência | Zona de soltar só funcionava com mouse. Sem atalhos. | Zona de soltar acessível por teclado, `/` foca a busca, Ctrl+Enter envia, exemplos de busca clicáveis. |
| 8 | Estética e design minimalista | Quatro blocos de igual peso numa rolagem só. | Quatro telas (Transcrever, Buscar, Glossário, Vozes) com uma tarefa cada. Opções raras ficam em "Mais opções". |
| 9 | Ajudar a reconhecer, diagnosticar e corrigir erros | "Erro: 400" e mensagens técnicas cruas dentro de uma célula de tabela. Falhas de rede eram silenciosas. | Mensagens em linguagem simples dizendo o que fazer, com o detalhe técnico recolhido. Falha de rede e falha de busca viram aviso na tela. |
| 10 | Ajuda e documentação | Nenhuma. | Texto de apoio em cada tela, estados vazios que explicam o próximo passo, e a tela Vozes com os comandos para cadastrar. |

Além das heurísticas: foco visível em todos os controles, alvos de toque de pelo menos 40 px, contraste conferido nos dois temas, texto de estado nunca só por cor, respeito a `prefers-reduced-motion`.

**Links de vídeo e resumo (24/10/2026), pelas mesmas heurísticas:** o campo de links valida cada linha antes de enviar e diz qual linha está errada (5, prevenção de erros). A fila mostra a etapa em andamento: baixando, transcrevendo ou resumindo (1, visibilidade). Um link que falha vira aviso e o resto do envio segue; se o resumo falhar, a transcrição já está salva (9, recuperar de erros). Mensagens de erro do download dizem o que fazer, por exemplo enviar o arquivo no lugar do link quando o YouTube pede verificação anti-robô. "Resumir depois" fica desligada, com o motivo, quando o Ollama não está aberto (6, reconhecer em vez de lembrar).

Tudo é servido localmente: nenhuma fonte, script ou imagem vem de CDN, o que preserva a promessa "os áudios não saem daqui" e funciona sem internet. Um teste automático falha se a página passar a apontar para um endereço externo.
