# Álbum de Memórias 3D — V6 compartilhado 💞

Dois participantes, um único livro: fotos e textos salvos no Supabase privado, sincronização em tempo real e interface responsiva. O código pode ser hospedado gratuitamente como site estático (GitHub Pages); **as fotos não são enviadas para o GitHub**.

## Requisitos

Node.js 20.19+ ou 22.12+. Projeto gratuito do Supabase. Dois endereços de e-mail.

## Configuração segura (sem gastar dinheiro)

1. Crie um projeto em https://supabase.com/dashboard e anote o **Project URL** e a **Publishable key** (pública, não uma chave secreta).
2. Na aba SQL Editor, execute `supabase/001_album_privado.sql`. Isso cria a tabela de páginas com RLS, o bucket privado `album-private` e a sincronização Realtime.
3. **Ainda no SQL Editor, somente no painel do Supabase**, adicione os dois e-mails autorizados. Nunca salve esses e-mails no GitHub:

   ```sql
   insert into private.couple_allowlist(email, role) values
     ('seu-email@exemplo.com', 'owner'),
     ('email-da-namorada@exemplo.com', 'partner');
   ```

4. Na aba Authentication > URL Configuration do Supabase, configure **Site URL** e **Redirect URLs** para incluir o endereço do GitHub Pages (quando publicado): `https://marcos-pds.github.io/trabalhadors-AI/`. Para testar localmente, inclua `http://127.0.0.1:5173/`.
5. Na pasta deste projeto, copie `.env.example` para `.env.local` e preencha **apenas** `VITE_SUPABASE_URL` e `VITE_SUPABASE_PUBLISHABLE_KEY`. Não coloque `service_role` nem `sb_secret_` no frontend.
6. Execute:

   ```powershell
   npm install
   npm test
   npm run build
   npm run dev
   ```

7. Abra o endereço indicado pelo Vite. Faça login pelos dois e-mails. Se o provedor mandar um link, clique nele; se o modelo de e-mail contiver um código OTP, também é possível digitá-lo.

## Publicar com GitHub Pages

O repositório existente pode ter outro site — **não altere a configuração do Pages nem rode o fluxo de deploy sem verificar se isso substituirá um site já publicado**. Um workflow manual de publicação do álbum fica em `.github/workflows/album-pages.yml` na raiz do repositório, caso seja adicionado.

O modo Pages recebe apenas a URL e a chave **publicável** do Supabase por meio de `.env.pages` (esses dados são intencionalmente públicos no navegador). O acesso às fotos exige autenticação e RLS. **Nunca comite chaves secretas, `service_role` ou senhas**. O desenvolvimento local continua usando `.env.local`.

No GitHub > Settings > Pages, selecione Source = GitHub Actions. O site será publicado em `https://marcos-pds.github.io/trabalhadors-AI/` após sucesso do workflow e configuração Pages. **Esse endereço ainda não é garantido até confirmação do deploy.**

## Privacidade e limitações

- Somente usuários com e-mail verificado e presente em `private.couple_allowlist` podem ler ou alterar as páginas, conforme a política RLS.
- As fotos ficam em bucket privado; o navegador recebe URLs assinadas válidas por 30 minutos, renovadas ao voltar para a aba e periodicamente. Quem receber uma URL assinada poderá usá-la até expirar; não a compartilhe.
- O site HTML/JS no Pages é público, mas as **memórias** estão protegidas no Supabase.
- Uma mesma página alterada simultaneamente pelas duas pessoas usa regra *última gravação vence*; lados diferentes não se sobrescrevem, pois são linhas separadas.
- As fotos são compactadas para reduzir consumo de armazenamento; trocar uma foto mantém o arquivo anterior no Storage até limpeza administrativa.
- O projeto Supabase gratuito tem limites de quota/inatividade. Faça backups periódicos pelo painel do Supabase.
- Se o Supabase não estiver configurado, existe apenas um modo **demonstração**, que não salva dados.

## Testes

`npm test` verifica o modelo de armazenamento de folhas e a remoção das URLs temporárias. `npm run build` valida a compilação. Os testes reais de login, isolamento por RLS, upload, dois celulares e sincronização dependem de um projeto Supabase configurado; testes isolados não garantem o funcionamento em produção.

## Check-list de aceitação para duas pessoas

- [ ] Os dois e-mails foram adicionados à allowlist **somente no SQL Editor** (não coloque e-mails em commits).
- [ ] Ambos recebem o link ou código de login e conseguem abrir o livro em navegadores separados.
- [ ] Pessoa A salva uma foto; após o indicador **Salvo na nuvem**, pessoa B recebe atualização sem atualizar a página.
- [ ] Pessoa B escreve uma mensagem; pessoa A vê a mensagem em seu dispositivo.
- [ ] Recarregar a página mantém textos e imagens.
- [ ] Um terceiro e-mail não vê páginas nem imagens (RLS efetiva).
- [ ] Testar celular (retrato), desktop e expiração/renovação das URLs assinadas.

### Publicação sem substituir outros sites do GitHub

O workflow manual em `.github/workflows/album-3d-pages.yml` publica um artefato no **único site GitHub Pages deste repositório**. Se já houver um site Pages nesse mesmo repositório, o novo deploy poderá substituí-lo. Antes de ativar, verifique a configuração existente ou prefira um repositório separado.


## Versão R & M — cadastro com aprovação

A capa inicial mostra **Rayssa & Marcos Paulo** e o monograma **R & M**.

- O proprietário entra com o e-mail previamente autorizado e vê um **sino** no canto superior direito quando o livro está aberto ou fechado.
- A pessoa convidada pode escolher **Criar conta**, informar nome, e-mail e senha e confirmar o e-mail.
- Após entrar, escolhe **Solicitar acesso ao álbum**. Isso cria um pedido **pendente**, sem acesso às fotos.
- O proprietário clica no sino e decide **Aprovar** ou **Recusar**. A aprovação libera apenas uma pessoa parceira, sem alterar a privacidade do álbum.
- A tela de espera consulta periodicamente o estado da solicitação. Ao ser aprovada, a pessoa entra automaticamente no álbum.
- O e-mail da convidada **não precisa ser informado antecipadamente** e não é adicionado ao GitHub.

### Atenção: configurar confirmação de e-mail

Em Supabase > Authentication > Providers > Email:
- Deixe **Confirm Email** habilitado para impedir identidades não verificadas.
- Certifique-se de que novas contas podem se cadastrar. Os pedidos ficam limitados por RLS e a autorização só acontece após aprovação.

Em Supabase > Authentication > URL Configuration:
- **Site URL:** \`https://marcos-pds.github.io/trabalhadors-AI/\`
- **Redirect URLs:** adicione \`https://marcos-pds.github.io/trabalhadors-AI/\` e, se quiser testar localmente, \`http://127.0.0.1:5173/\`.

### Publicação gratuita no GitHub Pages

A partir desta atualização, o workflow \`.github/workflows/album-3d-pages.yml\` tenta publicar automaticamente quando os arquivos do álbum são alterados na branch principal.

No GitHub, em **Settings → Pages**, defina a origem **GitHub Actions**. Essa configuração exige permissão de proprietário e não pode ser realizada por este conector. Se outro site já usava o GitHub Pages deste repositório, ele será substituído pelo álbum.

Somente considerar o endereço \`https://marcos-pds.github.io/trabalhadors-AI/\` **ativo após o deploy concluir com sucesso**. O código pode ser público; as fotos são privadas por RLS e por bucket privado.

### Migration

A estrutura nova para aprovação está em \`supabase/002_acesso_com_aprovacao.sql\` e foi aplicada ao projeto Supabase \`album-de-memorias\`.
