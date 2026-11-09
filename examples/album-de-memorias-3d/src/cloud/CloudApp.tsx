import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import Album, { createRandomEditablePage, defaultAlbumData, type AlbumSheet, type PageData } from '../App';
import { fromRows, makeInitialRows, toRow, type AlbumPageRow } from './albumRows';
import { signedPhotoUrls, uploadPrivatePhoto } from './photos';
import { cloudConfigured, supabase } from './supabase';
import { AccessGate, PendingAccess, ApprovalBell } from './AccessPortal';

const uiStyle: CSSProperties = {
  position: 'fixed', zIndex: 3000, top: 14, left: 14, right: 14, display: 'flex', alignItems: 'center',
  justifyContent: 'space-between', gap: 12, pointerEvents: 'none', fontFamily: 'Inter, sans-serif'
};
const buttonStyle: CSSProperties = { padding: '10px 16px', borderRadius: 10, background: '#713037', color: '#fff', border: '1px solid #a76e70', cursor: 'pointer' };

function CenterPanel({ children }: { children: ReactNode }) {
  return <div style={{ minHeight: '100svh', display: 'grid', placeItems: 'center', background: 'radial-gradient(circle at 50% 10%, #44303b, #100c13)', color: '#fff', padding: 20 }}>
    <div style={{ width: 'min(450px, 100%)', padding: 30, background: '#ffffff12', border: '1px solid #ffffff26', borderRadius: 22, boxShadow: '0 20px 80px #0006', fontFamily: 'Inter, sans-serif', lineHeight: 1.55 }}>{children}</div>
  </div>;
}

export default function CloudApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [allowed, setAllowed] = useState(false);
  const [role, setRole] = useState<string | null>(null);
  const [approvalTick, setApprovalTick] = useState(0);
  const [loadingAlbum, setLoadingAlbum] = useState(false);
  const [status, setStatus] = useState('Conectando…');
  const [notice, setNotice] = useState('');
  const [demo, setDemo] = useState(false);
  const [sheets, setSheets] = useState<AlbumSheet[]>([]);
  const sheetsRef = useRef<AlbumSheet[]>([]);
  const pendingRef = useRef(new Map<string, AlbumPageRow>());
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savingRef = useRef(false);
  const remoteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seqRef = useRef(11);

  const assignSheets = useCallback((next: AlbumSheet[]) => {
    sheetsRef.current = next;
    setSheets(next);
    seqRef.current = Math.max(11, ...next.flatMap(s => [s.front.pageNumber || 0, s.back.pageNumber || 0]).map(n => n + 1));
  }, []);

  const fetchAlbum = useCallback(async (initialize = false) => {
    if (!supabase) return;
    const { data: raw, error } = await supabase.from('album_pages').select('*').order('position', { ascending: true });
    if (error) throw error;
    let rows = (raw || []) as AlbumPageRow[];
    if (!rows.length && initialize) {
      const seed = makeInitialRows(defaultAlbumData, (await supabase.auth.getUser()).data.user?.id ?? '');
      const { error: bootError } = await supabase.from('album_pages').upsert(seed, { onConflict: 'sheet_id,side', ignoreDuplicates: true });
      if (bootError) throw bootError;
      const { data: reloaded, error: reloadError } = await supabase.from('album_pages').select('*').order('position', { ascending: true });
      if (reloadError) throw reloadError;
      rows = (reloaded || []) as AlbumPageRow[];
    }
    const paths = rows.map(r => r.photo_path).filter((p): p is string => Boolean(p));
    const signed = await signedPhotoUrls(paths);
    const next = fromRows(rows, signed);
    // Preserve local edits still queued for upload if remote events arrive simultaneously.
    for (const local of pendingRef.current.values()) {
      const index = next.findIndex(s => s.id === local.sheet_id);
      if (index !== -1) {
        next[index] = {
          ...next[index],
          [local.side]: {
            ...local.content,
            photoPath: local.photo_path ?? undefined,
            imageUrl: sheetsRef.current.find(s => s.id === local.sheet_id)?.[local.side].imageUrl
          }
        };
      }
    }
    assignSheets(next);
  }, [assignSheets]);

  const flushPending = useCallback(async () => {
    if (!supabase || savingRef.current || pendingRef.current.size === 0) return;
    savingRef.current = true;
    const batch = [...pendingRef.current.values()];
    pendingRef.current.clear();
    try {
      const { error } = await supabase.from('album_pages').upsert(batch, { onConflict: 'sheet_id,side' });
      if (error) throw error;
      setStatus('Salvo na nuvem ✓');
    } catch (error) {
      for (const row of batch) {
        const key = `${row.sheet_id}:${row.side}`;
        if (!pendingRef.current.has(key)) pendingRef.current.set(key, row);
      }
      setStatus('Erro ao salvar');
      setNotice(error instanceof Error ? error.message : 'Falha na sincronização. Tente novamente.');
    } finally {
      savingRef.current = false;
      if (pendingRef.current.size > 0) {
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => { void flushPending(); }, 1500);
      }
    }
  }, []);

  const queueRow = useCallback((row: AlbumPageRow) => {
    pendingRef.current.set(`${row.sheet_id}:${row.side}`, row);
    setStatus('Salvando…');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => { void flushPending(); }, 650);
  }, [flushPending]);

  useEffect(() => {
    if (!supabase) { setCheckingAuth(false); return; }
    let mounted = true;
    void supabase.auth.getSession().then(({ data, error }) => {
      if (mounted) {
        if (error) setNotice(error.message);
        setSession(data.session);
        setCheckingAuth(false);
      }
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, next) => {
      if (mounted) { setSession(next); setCheckingAuth(false); }
    });
    return () => { mounted = false; subscription.unsubscribe(); };
  }, []);

  useEffect(() => {
    if (!supabase || !session) { setAllowed(false); setRole(null); return; }
    let active = true;
    setLoadingAlbum(true);
    const initialize = async () => {
      try {
        const { data, error } = await supabase!.rpc('album_my_role');
        if (error) throw error;
        if (!active) return;
        setRole(data || null);
        setAllowed(Boolean(data));
        if (!data) { setStatus('Acesso não autorizado'); return; }
        await fetchAlbum(true);
        if (active) setStatus('Sincronizado ✓');
      } catch (error) {
        if (active) {
          setStatus('Configuração incompleta');
          setNotice(error instanceof Error ? error.message : 'Não foi possível abrir o álbum.');
        }
      } finally {
        if (active) setLoadingAlbum(false);
      }
    };
    void initialize();
    return () => { active = false; };
  }, [session?.user.id, fetchAlbum, approvalTick]);

  useEffect(() => {
    if (!supabase || !allowed || !session) return;
    const channel = supabase.channel('nosso-album')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'album_pages' }, (change) => {
        const updatedBy = (change.new as { updated_by?: string }).updated_by;
        if (updatedBy && updatedBy === session.user.id) return;
        if (remoteTimerRef.current) clearTimeout(remoteTimerRef.current);
        remoteTimerRef.current = setTimeout(() => {
          void fetchAlbum().catch(error => setNotice(error instanceof Error ? error.message : 'Falha ao atualizar.'));
        }, 350);
      })
      .subscribe((state) => {
        if (state === 'SUBSCRIBED') setStatus(old => old === 'Erro ao salvar' ? old : 'Conectado em tempo real ✓');
        if (state === 'CHANNEL_ERROR' || state === 'TIMED_OUT') setStatus('Reconectando…');
      });
    const onVisible = () => {
      if (document.visibilityState === 'visible') void fetchAlbum().catch(() => setStatus('Erro ao atualizar fotos'));
    };
    document.addEventListener('visibilitychange', onVisible);
    const renewal = setInterval(onVisible, 20 * 60 * 1000);
    return () => {
      void supabase!.removeChannel(channel);
      document.removeEventListener('visibilitychange', onVisible);
      clearInterval(renewal);
      if (remoteTimerRef.current) clearTimeout(remoteTimerRef.current);
    };
  }, [allowed, session?.user.id, fetchAlbum]);

  useEffect(() => () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    if (remoteTimerRef.current) clearTimeout(remoteTimerRef.current);
    void flushPending();
  }, [flushPending]);

  const updatePage = (sheet: AlbumSheet, side: 'front' | 'back', page: PageData, position: number) => {
    if (!session) return;
    const next = sheetsRef.current.map(s => s.id === sheet.id ? { ...s, [side]: page } : s);
    assignSheets(next);
    queueRow(toRow({ ...sheet, [side]: page }, side, position, session.user.id));
  };

  const addSheet = () => {
    if (!session) return;
    const frontPage = seqRef.current++;
    const backPage = seqRef.current++;
    const sheet: AlbumSheet = {
      id: `sheet-${crypto.randomUUID()}`,
      front: createRandomEditablePage(frontPage),
      back: createRandomEditablePage(backPage)
    };
    const position = sheetsRef.current.length;
    assignSheets([...sheetsRef.current, sheet]);
    queueRow(toRow(sheet, 'front', position, session.user.id));
    queueRow(toRow(sheet, 'back', position, session.user.id));
  };

  if (!cloudConfigured) {
    return demo ? <div><div style={uiStyle}><span style={{ color: '#fff', pointerEvents: 'auto' }}>Modo demonstração — fotos não ficam salvas</span><button onClick={() => setDemo(false)} style={{ ...buttonStyle, pointerEvents: 'auto' }}>Sair da demonstração</button></div><Album /></div> :
      <CenterPanel>
        <h1>💌 Álbum compartilhado</h1>
        <p>O projeto está pronto para a integração, mas o banco privado ainda não foi conectado.</p>
        <p>Configure <code>VITE_SUPABASE_URL</code> e <code>VITE_SUPABASE_PUBLISHABLE_KEY</code> depois de executar a migração SQL no Supabase. Nenhuma foto privada vai para o GitHub.</p>
        <button onClick={() => setDemo(true)} style={buttonStyle}>Ver demonstração (não salva)</button>
      </CenterPanel>;
  }
  if (checkingAuth) return <CenterPanel><p>Preparando seu álbum…</p></CenterPanel>;
  if (!session) return <><AccessGate onNotice={setNotice} />{notice && <div role="alert" style={{ position: 'fixed', bottom: 15, left: 15, right: 15, padding: 12, background: '#733b41', color: 'white', borderRadius: 10, zIndex: 4000 }}>{notice}</div>}</>;
  if (loadingAlbum) return <CenterPanel><p>Carregando as memórias compartilhadas…</p></CenterPanel>;
  if (!allowed) return <>
    <PendingAccess session={session} onNotice={setNotice} onApproved={() => setApprovalTick(v => v + 1)} />
    {notice && <div role="alert" style={{ position: 'fixed', bottom: 15, left: 15, right: 15, padding: 12, background: '#733b41', color: 'white', borderRadius: 10, zIndex: 4000, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <span>{notice}</span><button type="button" onClick={() => setNotice('')} style={{ color: '#fff', background: 'transparent', border: 0 }}>✕</button>
    </div>}
  </>;

  return <>
    <div style={uiStyle}>
      <div style={{ background: '#291b25cf', borderRadius: 14, padding: '8px 12px', border: '1px solid #ffffff26', pointerEvents: 'auto', color: '#fff', fontSize: 12 }}>
        <strong>💞 Nosso álbum</strong> · {status}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, pointerEvents: 'auto' }}>
        {role === 'owner' && <ApprovalBell onNotice={setNotice} />}
        <button style={{ ...buttonStyle, padding: '7px 12px', background: '#291b25d5', fontSize: 12 }} onClick={async () => { await flushPending(); await supabase?.auth.signOut(); }}>Sair</button>
      </div>
    </div>
    <Album controlledSheets={sheets} onUpdatePage={updatePage} onCreateSheet={addSheet}
      onUploadPhoto={async (_index, _side, file) => uploadPrivatePhoto(file, session.user.id)}
      onPhotoError={setNotice} />
    {notice && <div role="alert" style={{ position: 'fixed', bottom: 15, left: 15, right: 15, padding: 12, background: '#733b41', color: 'white', borderRadius: 10, zIndex: 4000, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
      <span>{notice}</span><button style={{ background: 'transparent', color: '#fff', border: 0, cursor: 'pointer' }} onClick={() => setNotice('')}>✕</button>
    </div>}
  </>;
}
