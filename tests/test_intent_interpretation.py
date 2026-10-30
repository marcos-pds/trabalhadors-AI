"""Natural requests are routed to tools; questions do not authorize writes."""
import pytest

from central.run_policy import classify_task
from central.task_contract import (
    is_implementation_request, is_continuation_request,
    resolve_continuation_prompt, requested_text_change,
)


@pytest.mark.parametrize('prompt', [
    'Altere o título para Olá mundo',
    'Faça o botão ficar maior',
    'Faz uma página de login',
    'Monte um dashboard com filtros',
    'Mude o título do projeto para Meu app',
    'Troque o texto do botão para Começar',
    'Substitua o subtítulo por Tecnologia para todos',
    'Atualize o placeholder para Seu nome',
    'Renomeie o arquivo App.tsx para Home.tsx',
    'Ajuste o espaçamento entre os cards',
    'Melhore a tipografia da página',
    'Arrume o menu mobile',
    'Repare o formulário de contato',
    'Otimize o código da busca',
    'Organize os componentes do projeto',
    'Alinhe o botão à direita',
    'Centralize o logo',
    'Aumente a fonte do cabeçalho',
    'Diminua o tamanho da imagem',
    'Reduza o padding do card',
    'Amplie a prévia para metade da tela',
    'Deixe o fundo azul',
    'Torne a página responsiva',
    'Coloque um ícone no botão',
    'Inclua um campo de telefone no formulário',
    'Insira um filtro de tarefas',
    'Remova o card duplicado',
    'Retire o link do rodapé',
    'Oculte os logs',
    'Exiba o menu no celular',
    'Mova a sidebar para a esquerda',
    'Reordene os campos do formulário',
    'Habilite a busca',
    'Desabilite a animação do título',
    'Ative o filtro de tarefas',
    'Desative o botão enquanto estiver enviando',
    'Conecte o formulário à API',
    'Integre o endpoint de cadastro',
    'Configure os testes do projeto',
    'deixa o botão maior',
    'troca a cor do fundo',
    'coloca um menu',
    'tira a imagem do header',
    'bota um ícone no botão',
    'Pode corrigir o formulário?',
    'Você poderia mudar a cor do botão?',
    'Por favor, ajuste o App.tsx',
    'Quero o fundo azul',
    'Quero que o botão fique maior',
    'Preciso que o menu funcione',
    'Gostaria que a tela fosse responsiva, torne a página responsiva',
    'O título deve ser Minha empresa',
    'O fundo deve ficar escuro',
    'Corrija src/helpers.ts',
    'Ajuste "src/App.tsx"',
    "Corrija 'src/helpers.ts'",
    'Refatore `utils.py`',
    'Fix the login button',
    'Update the page title',
    'Replace the background color',
    'Add a menu to the website',
    'Não mude o layout, mas corrija o botão',
    'Não altere o título, troque a cor do botão',
    'Explique o erro e depois corrija o código',
    'Analise os arquivos e implemente a correção do formulário',
    'Crie o site. Não altere arquivos fora do workspace.',
    'Corrija o botão sem alterar arquivos de outros projetos.',
])
def test_natural_change_requests_require_real_implementation(prompt):
    result = classify_task(prompt, autonomous=True)
    assert result['task_type'] == 'code', (prompt, result)
    assert result['recommended_review']


@pytest.mark.parametrize('prompt', [
    'Explique como mudar o título',
    'Como posso alterar o botão?',
    'Como corrigir o formulário?',
    'Você sabe como criar uma API?',
    'Seria possível mudar o layout?',
    'Talvez aumentar a fonte do título seja uma boa ideia',
    'Sugira como melhorar o menu',
    'Me dê ideias de um ecommerce',
    'Crie um prompt para alterar o título da página',
    'Faça um prompt para melhorar o site',
    'Prepare um prompt para corrigir a página',
    'Quero saber como mudar o fundo',
    'Quero entender como remover o botão',
    'Quero uma explicação sobre como corrigir o projeto',
    'Não altere o título',
    'Não quero que mude o título',
    'Não precisa alterar o botão',
    'Não mude o layout, apenas explique',
    'Planeje o sistema sem modificar arquivos',
    'Analise o projeto sem alterar código',
    'Corrija o projeto sem alterar arquivos',
    'A documentação contém "remova o botão" como exemplo',
    'Exemplo:\n```\nAltere o título para Minha empresa\n```',
    'How do I change the page title?',
    'Explain how to fix this button',
    'Do not remove the button',
    "Don't change the page title",
])
def test_explanations_examples_and_negations_do_not_authorize_implementation(prompt):
    assert not is_implementation_request(prompt), prompt


@pytest.mark.parametrize('prompt', [
    'Analise o projeto',
    'Diagnostique o formulário',
    'Investigue o erro no código',
    'Revise o App.tsx',
    'Avalie a interface',
    'Identifique bugs no site',
    'Encontre o arquivo do título',
    'Mostre os arquivos da pasta',
    'Leia o código do endpoint',
])
def test_diagnostics_use_read_tools_without_implementation_requirement(prompt):
    assert classify_task(prompt, autonomous=True)['task_type'] == 'inspection'


@pytest.mark.parametrize('prompt', ['continue', 'prossiga', 'retome', 'agora continue', 'continue o prjeto'])
def test_short_continuations_are_recognized(prompt):
    assert is_continuation_request(prompt)


def test_context_is_resolved_only_inside_the_same_conversation():
    from central.database import Database, utcnow
    db = Database(':memory:')
    now = utcnow()
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)', ('u', 'u@example.com', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', ('chat', 'u', 'App', None, now, now))
        db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('old', 'u', 'chat', 'Aumente a fonte do título', 'completed', 'auto', '[]', '[]', now, now))
        for prompt in ('continue', 'deixe maior'):
            expanded = resolve_continuation_prompt(db, 'chat', prompt)
            assert prompt in expanded
            assert is_implementation_request(expanded)
            assert resolve_continuation_prompt(db, 'other-chat', prompt) == prompt
        assert resolve_continuation_prompt(db, 'chat', 'só explique') == 'só explique'
        assert resolve_continuation_prompt(db, 'chat', 'não mude nada') == 'não mude nada'
    finally:
        db.close()


def test_current_copy_request_preserves_case_and_accents():
    assert requested_text_change('Altere o título para "Olá, São Paulo!"')['text'] == 'Olá, São Paulo!'


def test_multiple_requirements_do_not_become_one_literal_heading():
    prompt = 'Mude o título para Olá e remova o menu'
    assert is_implementation_request(prompt)
    assert requested_text_change(prompt) is None
    assert requested_text_change('Mude o título para "Olá e remova o menu"')['text'] == 'Olá e remova o menu'


def test_conceptual_review_can_remain_a_conversation():
    assert classify_task('Revise o fluxo de autenticação e login')['task_type'] == 'conversation'
    assert classify_task('Revise o fluxo de autenticação no código do projeto')['task_type'] == 'inspection'
