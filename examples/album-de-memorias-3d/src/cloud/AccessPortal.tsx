import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from './supabase';

type Notice = (message: string) => void;
type RequestRow = {
  id: string;
  requester_id: string;
  display_name: string;
  email: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
};

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '13px 15px', border: '1px solid #dcc8b5',
  borderRadius: 12, background: '#fff9f2', color: '#442b30',
  fontSize: 15, outlineColor: '#b48a53', boxSizing: 'border-box'
};
const buttonStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
  padding: '13px 17px', border: '1px solid #c19b64', borderRadius: 12,
  background: 'linear-gradient(130deg, #7b3540, #54202a)', color: '#fff2d9',
  fontWeight: 600, cursor: 'pointer', fontSize: 14
};
const subtleButton: React.CSSProperties = {
  ...buttonStyle, background: 'rgba(255,255,255,.08)', borderColor: '#ffffff40',
  color: '#fff3e1'
};

function Layout({ children }: { children: ReactNode }) {
  return <div style={{
    minHeight: '100svh', padding: '36px 18px', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: 'radial-gradient(circle at 50% 15%,#4b333c,#160c15 72%)',
    color: '#fff2e7', fontFamily: 'Inter, system-ui, sans-serif', boxSizing: 'border-box'
  }}>
    <div style={{
      width: 'min(440px, 100%)', padding: 'clamp(22px, 5vw, 36px)', borderRadius: 24,
      background: 'linear-gradient(155deg,rgba(255,255,255,.13),rgba(255,255,255,.04))',
      border: '1px solid rgba(241,218,191,.26)', boxShadow: '0 28px 90px #0008',
      backdropFilter: 'blur(18px)'
    }}>{children}</div>
  </div>;
}

const field = (caption: string, control: ReactNode) => <label style={{ display: 'grid', gap: 6, fontSize: 13, color: '#ead9d1' }}>{caption}{control}</label>;
const authRedirect = () => new URL(import.meta.env.BASE_URL, window.location.origin).toString();

export function AccessGate({ onNotice }: { onNotice: Notice }) {
  const [view, setView] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setMessage('');
    try {
      if (view === 'signup') {
        if (name.trim().length < 2) throw new Error('Informe seu nome.');
        if (password.length < 8) throw new Error('Use uma senha com pelo menos 8 caracteres.');
        const { error } = await supabase.auth.signUp({
          email: email.trim().toLowerCase(), password,
          options: { data: { full_name: name.trim().slice(0, 60) }, emailRedirectTo: authRedirect() }
        });
        if (error) throw error;
        setMessage('Conta criada. Verifique sua caixa de entrada e confirme o e-mail. Depois volte para entrar e pedir acesso.');
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (error) throw error;
      }
    } catch (err) { onNotice(err instanceof Error ? err.message : 'Não foi possível continuar.'); }
    finally { setBusy(false); }
  };

  const magicLink = async () => {
    if (!supabase || !email.trim()) { onNotice('Digite seu e-mail primeiro.'); return; }
    setBusy(true);
    try {
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim().toLowerCase(),
        options: { shouldCreateUser: true, emailRedirectTo: authRedirect() }
      });
      if (error) throw error;
      setMessage('Enviamos um link de acesso para seu e-mail. Depois de clicar, você poderá pedir aprovação.');
    } catch (err) { onNotice(err instanceof Error ? err.message : 'Não foi possível enviar o link.'); }
    finally { setBusy(false); }
  };

  return <Layout>
    <div style={{ textAlign: 'center', marginBottom: 23 }}>
      <div style={{ fontFamily: 'Georgia,serif', color: '#e6c68d', fontSize: 46, letterSpacing: 7 }}>R &amp; M</div>
      <div style={{ fontFamily: 'Georgia,serif', fontSize: 24, marginTop: 7 }}>Rayssa &amp; Marcos Paulo</div>
      <p style={{ fontSize: 13, color: '#dbc9c6', marginTop: 8 }}>Nosso livro de memórias • um lugar só nosso</p>
    </div>

    <div style={{ display: 'flex', padding: 4, borderRadius: 13, background: '#ffffff12', marginBottom: 24, gap: 4 }}>
      {(['login','signup'] as const).map(option => <button key={option} type="button"
        onClick={() => { setView(option); setMessage(''); }}
        style={{ flex: 1, borderRadius: 10, padding: 10, cursor: 'pointer', border: 0,
          background: view === option ? '#f4e8d7' : 'transparent', color: view === option ? '#532a32' : '#f9e9da', fontWeight: 600 }}>
        {option === 'login' ? 'Entrar' : 'Criar conta'}
      </button>)}
    </div>

    <form onSubmit={submit} style={{ display: 'grid', gap: 15 }}>
      {view === 'signup' && field('Seu nome', <input autoComplete="name" required minLength={2} maxLength={60}
        value={name} onChange={e => setName(e.target.value)} style={inputStyle} placeholder="Seu nome" />)}
      {field('E-mail', <input type="email" autoComplete="email" required value={email}
        onChange={e => setEmail(e.target.value)} style={inputStyle} placeholder="voce@exemplo.com" />)}
      {field('Senha', <input type="password" autoComplete={view === 'signup' ? 'new-password' : 'current-password'}
        required minLength={view === 'signup' ? 8 : undefined} value={password}
        onChange={e => setPassword(e.target.value)} style={inputStyle} placeholder="••••••••" />)}
      <button disabled={busy} style={{ ...buttonStyle, opacity: busy ? 0.65 : 1 }}>
        {busy ? 'Aguarde…' : view === 'signup' ? 'Criar minha conta' : 'Entrar no álbum'}
      </button>
    </form>
    <button type="button" onClick={() => void magicLink()} disabled={busy}
      style={{ ...subtleButton, width: '100%', marginTop: 12, padding: 10 }}>
      Entrar por link no e-mail (sem senha)
    </button>
    {message && <p role="status" style={{ fontSize: 13, color: '#ffdfb4', lineHeight: 1.5 }}>{message}</p>}
    <p style={{ color: '#ccb9bc', fontSize: 12, lineHeight: 1.55, marginTop: 22, textAlign: 'center' }}>
      Criar uma conta não libera as fotos. Um pedido de acesso será enviado para aprovação do proprietário.
    </p>
  </Layout>;
}

export function PendingAccess({ session, onNotice, onApproved }: { session: Session; onNotice: Notice; onApproved: () => void }) {
  const [request, setRequest] = useState<RequestRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const check = async () => {
    if (!supabase) return;
    try {
      const { data: role, error: roleError } = await supabase.rpc('album_my_role');
      if (roleError) throw roleError;
      if (role) { onApproved(); return; }
      const { data, error } = await supabase.from('album_access_requests')
        .select('id, requester_id, display_name, email, status, created_at')
        .eq('requester_id', session.user.id).maybeSingle();
      if (error) throw error;
      setRequest(data as RequestRow | null);
    } catch (err) { onNotice(err instanceof Error ? err.message : 'Não foi possível consultar o pedido.'); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    setLoading(true);
    void check();
    const interval = window.setInterval(() => { void check(); }, 12000);
    const onFocus = () => { void check(); };
    window.addEventListener('focus', onFocus);
    return () => { clearInterval(interval); window.removeEventListener('focus', onFocus); };
  }, [session.user.id]);

  const requestAccess = async () => {
    if (!supabase) return;
    setBusy(true);
    try {
      const fallback = session.user.email?.split('@')[0] || 'Convidada';
      const raw = String(session.user.user_metadata?.full_name || fallback).trim().slice(0, 60);
      const name = raw.length >= 2 ? raw : 'Convidada';
      const { error } = await supabase.from('album_access_requests').insert({
        requester_id: session.user.id,
        email: session.user.email?.trim().toLowerCase(),
        display_name: name,
        status: 'pending'
      });
      if (error && error.code !== '23505') throw error;
      await check();
      onNotice('Pedido enviado! O proprietário poderá aprovar pelo sino.');
    } catch (err) { onNotice(err instanceof Error ? err.message : 'Não foi possível enviar o pedido.'); }
    finally { setBusy(false); }
  };

  return <Layout>
    <div style={{ textAlign: 'center', fontSize: 40 }}>💌</div>
    <h1 style={{ fontFamily: 'Georgia,serif', textAlign: 'center', fontSize: 27, color: '#f0d3a8' }}>Nosso livro de memórias</h1>
    <p style={{ textAlign: 'center', lineHeight: 1.6, color: '#e7d3d3' }}>
      {loading ? 'Verificando seu acesso…' :
        request?.status === 'pending' ? 'Seu pedido está aguardando aprovação de Marcos Paulo. Você receberá acesso aqui assim que for aprovado.' :
        request?.status === 'rejected' ? 'Este pedido não foi aprovado. Converse com o proprietário para solicitar uma revisão.' :
        'Sua conta foi criada. Agora peça autorização para entrar no álbum.'}
    </p>
    {!loading && !request && <button style={{ ...buttonStyle, width: '100%' }} disabled={busy} onClick={() => void requestAccess()}>
      {busy ? 'Enviando…' : 'Solicitar acesso ao álbum'}
    </button>}
    <button style={{ ...subtleButton, width: '100%', marginTop: 12 }} onClick={() => void check()}>Verificar aprovação</button>
    <button style={{ ...subtleButton, width: '100%', marginTop: 12 }} onClick={() => void supabase?.auth.signOut()}>Sair da conta</button>
    <p style={{ fontSize: 12, color: '#c5b4b7', textAlign: 'center', marginTop: 22 }}>As fotografias permanecem privadas até a aprovação.</p>
  </Layout>;
}

export function ApprovalBell({ onNotice }: { onNotice: Notice }) {
  const [open, setOpen] = useState(false);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const load = async () => {
    if (!supabase) return;
    const { data, error } = await supabase.from('album_access_requests')
      .select('id,requester_id,display_name,email,status,created_at')
      .eq('status', 'pending').order('created_at', { ascending: true });
    if (error) { onNotice(error.message); return; }
    setRequests((data || []) as RequestRow[]);
  };

  useEffect(() => {
    if (!supabase) return;
    void load();
    const poll = window.setInterval(() => { void load(); }, 12000);
    const channel = supabase.channel('album-pedidos-aprovacao')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'album_access_requests' }, () => { void load(); })
      .subscribe();
    return () => { clearInterval(poll); void supabase?.removeChannel(channel); };
  }, []);

  const decide = async (requestId: string, decision: 'approved' | 'rejected') => {
    if (!supabase) return;
    setBusyId(requestId);
    try {
      const { error } = await supabase.rpc('review_album_request', { p_request_id: requestId, p_decision: decision });
      if (error) throw error;
      await load();
      onNotice(decision === 'approved' ? 'Acesso aprovado! Vocês já podem compartilhar memórias.' : 'Solicitação recusada.');
    } catch (err) { onNotice(err instanceof Error ? err.message : 'Não foi possível revisar o pedido.'); }
    finally { setBusyId(null); }
  };

  return <div style={{ position: 'relative', pointerEvents: 'auto' }}>
    <button type="button" onClick={() => setOpen(v => !v)} aria-label={'Pedidos de acesso: ' + requests.length}
      title="Pedidos para entrar no álbum" style={{ width: 39, height: 39, borderRadius: '50%', position: 'relative',
      border: '1px solid #ffffff40', color: '#f6dbaf', background: '#291b25ec', cursor: 'pointer',
      fontSize: 20, display: 'grid', placeItems: 'center' }}>
      <span aria-hidden="true" style={{ fontSize: 19, lineHeight: 1 }}>🔔</span>
      {requests.length > 0 && <span style={{ position: 'absolute', top: -6, right: -6, minWidth: 18, height: 18,
        background: '#b94854', borderRadius: 20, fontSize: 11, color: 'white',
        padding: '1px 4px', boxSizing: 'border-box' }}>{requests.length}</span>}
    </button>
    {open && <div role="region" aria-label="Solicitações de acesso" style={{ position: 'absolute', top: 49, right: 0,
      width: 'min(350px, calc(100vw - 24px))', maxHeight: 'min(440px, 65vh)', overflowY: 'auto',
      background: '#251820', border: '1px solid #8b6260', borderRadius: 16, boxShadow: '0 18px 60px #000a',
      padding: 17, color: '#fff0df', zIndex: 3100 }}>
      <div style={{ fontWeight: 700, marginBottom: 12 }}>Pedidos para entrar {requests.length ? '(' + requests.length + ')' : ''}</div>
      {requests.length === 0 && <div style={{ fontSize: 13, color: '#cdbbb8' }}>Nenhum pedido no momento. Um aviso aparecerá aqui quando ela solicitar acesso.</div>}
      {requests.map(req => <div key={req.id} style={{ borderTop: '1px solid #ffffff22', padding: '14px 0', display: 'grid', gap: 8 }}>
        <strong style={{ fontSize: 14 }}>{req.display_name}</strong>
        <span style={{ fontSize: 12, color: '#ddc7c8', overflowWrap: 'anywhere' }}>{req.email}</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button disabled={busyId !== null} onClick={() => void decide(req.id, 'approved')}
            style={{ ...buttonStyle, padding: '8px 11px', flex: 1 }}>Aprovar</button>
          <button disabled={busyId !== null} onClick={() => void decide(req.id, 'rejected')}
            style={{ ...subtleButton, padding: '8px 11px', flex: 1 }}>Recusar</button>
        </div>
      </div>)}
    </div>}
  </div>;
}
