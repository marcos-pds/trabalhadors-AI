import { PRIVATE_BUCKET, SIGNED_URL_TTL_SECONDS, supabase } from './supabase';

const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/webp']);

async function compressPhoto(file: File): Promise<Blob> {
  if (!allowedTypes.has(file.type)) throw new Error('Envie uma imagem JPG, PNG ou WebP.');
  if (file.size > 15 * 1024 * 1024) throw new Error('Escolha uma foto menor que 15 MB.');

  const bitmap = await createImageBitmap(file);
  try {
    const maxDimension = 1800;
    const scale = Math.min(1, maxDimension / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Este navegador não conseguiu preparar a fotografia.');
    // White background is intentional for PNGs with transparency.
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82));
    if (!blob || blob.size > 5 * 1024 * 1024) throw new Error('A foto é grande demais após a compressão.');
    return blob;
  } finally {
    bitmap.close();
  }
}

export async function uploadPrivatePhoto(file: File, userId: string): Promise<{ path: string; url: string }> {
  if (!supabase) throw new Error('Armazenamento não configurado.');
  const photo = await compressPhoto(file);
  const path = `photos/${userId}/${crypto.randomUUID()}.jpg`;
  const { error: uploadError } = await supabase.storage.from(PRIVATE_BUCKET).upload(path, photo, {
    upsert: false,
    contentType: 'image/jpeg',
    cacheControl: '1800'
  });
  if (uploadError) throw uploadError;
  const { data, error } = await supabase.storage.from(PRIVATE_BUCKET).createSignedUrl(path, SIGNED_URL_TTL_SECONDS);
  if (error || !data?.signedUrl) throw error ?? new Error('Foto salva, mas não foi possível gerar a prévia.');
  return { path, url: data.signedUrl };
}

export async function signedPhotoUrls(paths: string[]): Promise<Record<string, string>> {
  if (!supabase || paths.length === 0) return {};
  const unique = [...new Set(paths)].filter(Boolean);
  const { data, error } = await supabase.storage.from(PRIVATE_BUCKET).createSignedUrls(unique, SIGNED_URL_TTL_SECONDS);
  if (error) throw error;
  const urls: Record<string, string> = {};
  data?.forEach((entry, index) => {
    if (entry.signedUrl) urls[unique[index]] = entry.signedUrl;
  });
  return urls;
}
