"""Small deterministic starter templates; no shell commands are run."""
import json

def react_fastapi_files(name='Loja Virtual'):
    products = [
        {"id":1,"name":"Caneca Minimalista","description":"Cerâmica para o dia a dia.","price":49.90},
        {"id":2,"name":"Luminária de Mesa","description":"Design simples e funcional.","price":129.90},
        {"id":3,"name":"Organizador de Escritório","description":"Organize seu espaço.","price":39.90},
    ]
    backend = (
        "from fastapi import FastAPI\n"
        "from fastapi.middleware.cors import CORSMiddleware\n\n"
        "app = FastAPI(title='API Loja Virtual')\n"
        "app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173',"
        "'http://127.0.0.1:5173'], allow_credentials=False,"
        " allow_methods=['GET'], allow_headers=['*'])\n\n"
        "PRODUCTS = " + repr(products) + "\n\n"
        "@app.get('/api/health')\n"
        "def health():\n    return {'status': 'ok'}\n\n"
        "@app.get('/api/products')\n"
        "def list_products():\n    return PRODUCTS\n"
    )
    files = {
        'README.md': f"""# {name}

Projeto inicial funcional: React + Vite + TypeScript no frontend; FastAPI no backend.

## Rodar localmente (comandos MANUAIS, não executados pela Central)

### Backend — Python 3.11+

    cd backend
    python -m venv .venv
    .venv\\Scripts\\python -m pip install -r requirements.txt
    .venv\\Scripts\\python -m uvicorn main:app --reload

No Linux/macOS use .venv/bin/python no lugar de .venv\\Scripts\\python.

### Frontend — Node.js 20+

    cd frontend
    npm install
    npm run dev

Aplicação: http://localhost:5173 — API: http://localhost:8000/api/products

## Limitações
Produtos em memória (dados de demonstração), sem autenticação, pagamentos ou banco de dados.
Não coloque chaves de acesso nos arquivos. Revise toda alteração proposta por agentes antes de aplicá-la.
""",
        '.gitignore': "node_modules/\ndist/\n.venv/\n__pycache__/\n*.pyc\n.env\n.env.*\n!.env.example\n",
        'backend/requirements.txt': "fastapi>=0.115,<1\nuvicorn>=0.30,<1\n",
        'backend/main.py': backend,
        'frontend/package.json': json.dumps({
            "name":"loja-virtual", "private":True, "version":"0.1.0",
            "type":"module", "scripts":{"dev":"vite","build":"tsc -b && vite build","preview":"vite preview"},
            "dependencies":{"react":"^18.3.1","react-dom":"^18.3.1"},
            "devDependencies":{"@vitejs/plugin-react":"^4.4.0","vite":"^5.4.0",
                               "typescript":"~5.6.2","@types/react":"^18.3.0",
                               "@types/react-dom":"^18.3.0"}
        },indent=2)+"\n",
        'frontend/index.html': '<!doctype html>\n<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Loja Virtual</title></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>\n',
        'frontend/tsconfig.json': json.dumps({
            "compilerOptions":{"target":"ES2020","useDefineForClassFields":True,
              "lib":["ES2020","DOM","DOM.Iterable"],"module":"ESNext",
              "skipLibCheck":True,"moduleResolution":"Bundler",
              "allowImportingTsExtensions":True,"resolveJsonModule":True,"isolatedModules":True,
              "noEmit":True,"jsx":"react-jsx","strict":True,"esModuleInterop":True},
            "include":["src","vite.config.ts"]
        },indent=2)+"\n",
        'frontend/vite.config.ts': "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\nexport default defineConfig({ plugins: [react()] });\n",
        'frontend/src/main.tsx': "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App';\nimport './index.css';\nReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);\n",
        'frontend/src/api.ts': """export type Product = { id: number; name: string; description: string; price: number };
const BASE = 'http://127.0.0.1:8000';
export async function getProducts(): Promise<Product[]> {
  const response = await fetch(BASE + '/api/products');
  if (!response.ok) throw new Error('Falha ao carregar os produtos');
  return response.json() as Promise<Product[]>;
}
""",
        'frontend/src/App.tsx': """import { useEffect, useState } from 'react';
import { getProducts, type Product } from './api';

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    getProducts().then(setProducts).catch((err: unknown) =>
      setError(err instanceof Error ? err.message : 'Erro inesperado'));
  }, []);
  return <main className="container">
    <header><span className="eyebrow">Bem-vindo</span><h1>Loja Virtual</h1>
      <p>Uma vitrine simples e moderna, pronta para evoluir.</p></header>
    {error && <p role="alert">{error}. Inicie o backend na porta 8000.</p>}
    <section className="products" aria-label="Produtos">
      {products.map(p => <article className="product" key={p.id}>
        <div className="product-icon" aria-hidden="true">✦</div>
        <h2>{p.name}</h2><p>{p.description}</p>
        <strong>{p.price.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</strong>
      </article>)}
    </section>
  </main>;
}
""",
        'frontend/src/index.css': """*{box-sizing:border-box}body{margin:0;background:#0e1422;color:#edf0ff;font-family:system-ui,Arial,sans-serif}
.container{max-width:1100px;margin:0 auto;padding:56px 24px}h1{font-size:clamp(36px,6vw,68px);margin:12px 0}
header p,.product p{color:#a8b4c9}.eyebrow{color:#84e2ec;text-transform:uppercase;letter-spacing:.2em}
.products{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px;margin-top:50px}
.product{border:1px solid #34415b;background:#182237;padding:28px;border-radius:20px;min-height:235px}
.product h2{font-size:21px}.product strong{font-size:23px;color:#a7f3e5}
.product-icon{font-size:36px;color:#8f82ff} [role=alert]{color:#ffb9b9}
""",
    }
    return [{'path':path,'content':body,'action':'write'} for path,body in files.items()]
