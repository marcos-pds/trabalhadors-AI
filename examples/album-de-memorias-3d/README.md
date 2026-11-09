# Álbum de Memórias 3D — V5

Projeto independente de álbum 3D com React, TypeScript, Vite e Tailwind CSS.

## Funcionalidades

- Capa dura com abertura animada em 3D
- Navegação pelas extremidades das folhas, sem setas
- Folhas com frente e verso
- Adicionar fotografias e editar textos
- Molduras e layouts variados por folha
- Criação dinâmica de novas folhas
- Visual responsivo para desktop e celular
- Correções V5 para espelhamento e sobreposição de texto

## Executar localmente

```powershell
cd examples/album-de-memorias-3d
npm install
npm run dev
```

Depois abra o endereço indicado no terminal, normalmente `http://127.0.0.1:5173/`.

## Estado da versão

O arquivo TSX passou na análise de sintaxe. A aplicação React completa ainda não foi testada neste ambiente com suas dependências instaladas.

**Atenção:** imagens importadas usam URLs temporárias (`blob:`) e **não são persistidas** depois de atualizar o navegador. Publicar o código neste repositório não habilita automaticamente um site; para um link público funcional, é preciso configurar hospedagem e persistência.

Este exemplo está isolado em `examples/`, sem modificar a aplicação principal da Central de Trabalhadores IA.
