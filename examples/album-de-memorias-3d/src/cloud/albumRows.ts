import type { AlbumSheet, PageData } from '../App';

export type AlbumPageRow = {
  sheet_id: string;
  side: 'front' | 'back';
  position: number;
  content: Omit<PageData, 'imageUrl' | 'photoPath'>;
  photo_path: string | null;
  updated_by?: string;
};

export function toRow(sheet: AlbumSheet, side: 'front' | 'back', position: number, userId?: string): AlbumPageRow {
  // Never persist ephemeral browser blob URLs or signed Storage links in PostgreSQL.
  const { imageUrl: _imageUrl, photoPath, ...content } = sheet[side];
  return {
    sheet_id: sheet.id,
    side,
    position,
    content,
    photo_path: photoPath ?? null,
    ...(userId ? { updated_by: userId } : {})
  };
}

export function fromRows(rows: AlbumPageRow[], signedUrls: Record<string, string> = {}): AlbumSheet[] {
  const map = new Map<string, { position: number; sheet: AlbumSheet }>();
  for (const row of rows) {
    if (row.side !== 'front' && row.side !== 'back') continue;
    if (!map.has(row.sheet_id)) {
      map.set(row.sheet_id, {
        position: row.position,
        sheet: {
          id: row.sheet_id,
          front: { type: 'editable' },
          back: { type: 'editable' }
        }
      });
    }
    const entry = map.get(row.sheet_id)!;
    entry.position = Math.min(entry.position, row.position);
    entry.sheet[row.side] = {
      ...row.content,
      photoPath: row.photo_path ?? undefined,
      imageUrl: row.photo_path ? signedUrls[row.photo_path] : undefined
    };
  }
  return Array.from(map.values()).sort((a, b) => a.position - b.position || a.sheet.id.localeCompare(b.sheet.id)).map(v => v.sheet);
}

export function makeInitialRows(sheets: AlbumSheet[], userId: string): AlbumPageRow[] {
  return sheets.flatMap((sheet, index) => [toRow(sheet, 'front', index, userId), toRow(sheet, 'back', index, userId)]);
}
