import React, { useEffect, useMemo, useRef, useState } from 'react';

const globalStyles = `
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;1,400&family=Dancing+Script:wght@600&family=Inter:wght@300;400;500&display=swap');

  :root {
    --book-width: min(46vw, 69vh, 1350px);
    --book-height: calc(var(--book-width) * 1.28);
    --cover-color: #5c1a1b;
    --cover-deep: #2d0910;
    --cover-warm: #8c3434;
    --page-color: #f7f1e6;
    --page-ink: #4e392f;
    --gold: #d4af37;
    --book-thickness: 44px;
    --edge-hit: 54px;
  }

  @media (max-width: 900px) and (orientation: portrait) {
    :root {
      --book-width: min(91vw, 58vh, 700px);
      --book-height: min(77svh, calc(var(--book-width) * 1.65));
      --book-thickness: 24px;
      --edge-hit: 42px;
    }
  }

  @media (max-height: 550px) and (orientation: landscape) {
    :root {
      --book-width: min(44vw, 64svh, 480px);
      --book-height: calc(var(--book-width) * 1.28);
      --book-thickness: 20px;
      --edge-hit: 35px;
    }
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    overflow: hidden;
    background:
      radial-gradient(circle at 50% 28%, rgba(255,255,255,0.06), transparent 26%),
      radial-gradient(circle at 50% 120%, #281818 0%, #120d12 62%, #09070a 100%);
    color: #fff;
  }

  .scene {
    width: 100vw;
    height: 100vh;
    height: 100svh;
    display: flex;
    justify-content: center;
    align-items: center;
    perspective: 2300px;
    overflow: hidden;
    position: relative;
    background:
      radial-gradient(circle at top, rgba(255,244,220,0.10) 0%, transparent 30%),
      linear-gradient(180deg, #2d252d 0%, #171119 58%, #0d0911 100%);
  }

  .scene::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at center 82%, rgba(0,0,0,0.28), transparent 28%),
      radial-gradient(circle at 50% 10%, rgba(255,230,192,0.08), transparent 24%);
    pointer-events: none;
  }

  .book-shell {
    position: relative;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    transform-style: preserve-3d;
  }

  .book-container {
    position: relative;
    width: calc(var(--book-width) * 2);
    height: var(--book-height);
    transform-style: preserve-3d;
    transition: transform 0.85s cubic-bezier(0.25, 1, 0.5, 1);
  }

  .book-container.closed {
    transform: translateX(calc(-1 * var(--book-width) / 2)) rotateX(9deg) rotateY(-15deg) rotateZ(-2deg) scale(0.98);
    cursor: pointer;
  }

  .book-container.closed:hover {
    transform: translateX(calc(-1 * var(--book-width) / 2)) rotateX(8deg) rotateY(-12deg) rotateZ(-1deg) scale(1);
  }

  .book-container.open {
    transform: rotateX(6deg) rotateY(-1deg) scale(1);
  }

  /* Sem filter no ancestral 3D, evitando verso espelhado. */

  @media (max-width: 900px) and (orientation: portrait) {
    .book-container.open.mobile-focus-left {
      transform: translateX(calc(var(--book-width) / 2)) rotateX(3deg);
    }
    .book-container.open.mobile-focus-right {
      transform: translateX(calc(-1 * var(--book-width) / 2)) rotateX(3deg);
    }
    .book-shell.is-open { animation: none; }
    .edge-hit-area { pointer-events: none !important; }
  }

  .book-hardcover-back {
    position: absolute;
    inset: -6px -10px -8px auto;
    width: calc(var(--book-width) + 18px);
    background:
      linear-gradient(145deg, #2a0a0d 0%, #6c2326 18%, #8d3f41 52%, #3d1217 100%);
    border: 3px solid #2f0e13;
    border-radius: 9px 15px 15px 8px;
    transform: translateZ(calc(-1 * var(--book-thickness) - 4px));
    box-shadow:
      inset 0 0 0 1px rgba(255,255,255,0.06),
      inset -8px 0 20px rgba(255,255,255,0.06),
      inset 18px 0 30px rgba(0,0,0,0.23),
      0 18px 30px rgba(0,0,0,0.42);
    pointer-events: none;
    overflow: hidden;
  }

  .book-hardcover-back::before,
  .cover-shine {
    content: '';
    position: absolute;
    inset: 0;
    background:
      linear-gradient(110deg, transparent 0%, rgba(255,255,255,0.12) 15%, transparent 28%),
      radial-gradient(circle at 70% 25%, rgba(255,255,255,0.08), transparent 25%),
      repeating-linear-gradient(45deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.00) 5px, rgba(0,0,0,0.03) 7px, rgba(0,0,0,0.00) 12px);
    mix-blend-mode: screen;
    opacity: 0.65;
  }

  .book-spine {
    position: absolute;
    height: calc(100% + 14px);
    width: 32px;
    top: -7px;
    left: calc(50% - 16px);
    background: linear-gradient(90deg, #22070b, #8f3b3d 40%, #2c0a0e 100%);
    border-radius: 34%;
    transform: translateZ(calc(-1 * var(--book-thickness) - 1px));
    box-shadow: inset 0 0 12px rgba(0,0,0,0.6), inset 0 0 2px rgba(255,255,255,0.1);
    pointer-events: none;
  }

  .page-stack {
    --stack-thickness: 14px;
    position: absolute;
    width: var(--book-width);
    height: calc(var(--book-height) - 11px);
    top: 5px;
    background:
      linear-gradient(180deg, rgba(255,255,255,0.32), transparent 8%),
      repeating-linear-gradient(0deg, #fbf6ee 0px, #e7ddcf 1px, #fffaf2 2px, #eee3d2 3px);
    border: 1px solid #d7ccb9;
    box-shadow: 0 6px 14px rgba(24, 12, 10, 0.18);
    transform: translateZ(-9px);
    pointer-events: none;
  }

  .page-stack-left { left: 4px; border-radius: 8px 2px 2px 8px; }
  .page-stack-right { right: 4px; border-radius: 2px 8px 8px 2px; }

  .page-stack::before {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: var(--stack-thickness);
    background: repeating-linear-gradient(0deg, #faf3e7 0px, #e0d4bf 1px, #fef8ee 2px, #ede0cd 3px);
    border: 1px solid #cdbda7;
    transform: translateY(100%) rotateX(-84deg);
    transform-origin: top center;
  }

  .page-stack-left::after,
  .page-stack-right::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: var(--stack-thickness);
    background: repeating-linear-gradient(90deg, #fffaf0 0px, #e7dbc6 1px, #fff9eb 2px, #e8ddcb 3px);
    border: 1px solid #cdbda7;
  }

  .page-stack-right::after {
    right: 0;
    transform: translateX(100%) rotateY(82deg);
    transform-origin: left center;
  }

  .page-stack-left::after {
    left: 0;
    transform: translateX(-100%) rotateY(-82deg);
    transform-origin: right center;
  }

  .book-ground-shadow {
    position: absolute;
    width: 46%;
    height: 38px;
    bottom: -18px;
    left: 50%;
    transform: translateX(-50%);
    background: radial-gradient(ellipse at center, rgba(0,0,0,0.58), transparent 70%);
    filter: blur(12px);
    opacity: 0.9;
    pointer-events: none;
  }

  .book-shell.is-open .book-ground-shadow { width: 82%; bottom: -24px; }

  .mobile-nav-zone { display: none; }

  @media (max-width: 900px) and (orientation: portrait) {
    .mobile-nav-zone {
      display: block;
      position: absolute;
      top: 18%;
      bottom: 16%;
      z-index: 1000;
      width: max(22px, 8vw);
      border: none;
      background: transparent;
      padding: 0;
      touch-action: manipulation;
      -webkit-tap-highlight-color: transparent;
      cursor: pointer;
    }
    .mobile-nav-zone--left { left: 0; }
    .mobile-nav-zone--right { right: 0; }
  }

  .sheet {
    position: absolute;
    width: var(--book-width);
    height: var(--book-height);
    top: 0;
    right: 0;
    transform-origin: left center;
    transform-style: preserve-3d;
    transition: transform 1.1s cubic-bezier(0.38, 0.01, 0.25, 1);
    will-change: transform;
  }

  .sheet.turning .face { box-shadow: inset 0 0 30px rgba(0,0,0,0.13), 0 1px 18px rgba(0,0,0,0.18); }

  .face {
    position: absolute;
    width: 100%;
    height: 100%;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    background:
      radial-gradient(circle at 18% 12%, rgba(255,255,255,0.45), transparent 22%),
      radial-gradient(circle at 82% 78%, rgba(0,0,0,0.03), transparent 18%),
      linear-gradient(180deg, rgba(255,255,255,0.24), transparent 12%),
      var(--page-color);
    box-shadow:
      inset 0 0 0 1px rgba(99, 79, 56, 0.08),
      inset 0 0 25px rgba(67, 45, 28, 0.05);
    overflow: hidden;
    pointer-events: none;
  }

  .face.interactive { pointer-events: auto; }

  .face::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      repeating-linear-gradient(
        0deg,
        rgba(92,62,36,0.012) 0px,
        rgba(92,62,36,0.012) 1px,
        transparent 2px,
        transparent 4px
      );
    mix-blend-mode: multiply;
    opacity: 0.6;
    pointer-events: none;
  }

  .face-front {
    transform: translateZ(0.3px);
    border-radius: 2px 11px 11px 2px;
  }

  .face-back {
    transform: rotateY(180deg) translateZ(0.3px);
    border-radius: 11px 2px 2px 11px;
  }

  .sheet.is-cover .face-front {
    background:
      linear-gradient(145deg, #310b0f 0%, #6f2328 15%, #8b3b3d 45%, #3e1116 100%);
    border: 6px solid #421114;
    box-shadow:
      inset 0 0 0 1px rgba(255,255,255,0.06),
      inset -18px 0 28px rgba(255,255,255,0.05),
      inset 18px 0 25px rgba(0,0,0,0.28),
      8px 8px 20px rgba(0,0,0,0.40);
  }

  .sheet.is-cover .face-front::before {
    background:
      linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.11) 14%, transparent 28%),
      repeating-linear-gradient(45deg, rgba(255,255,255,0.02) 0px, rgba(255,255,255,0.00) 5px, rgba(0,0,0,0.03) 7px, rgba(0,0,0,0.00) 12px);
    opacity: 1;
    mix-blend-mode: screen;
  }

  .sheet.is-cover .face-back {
    background:
      radial-gradient(circle at 50% 20%, rgba(255,255,255,0.25), transparent 30%),
      linear-gradient(180deg, #f5ecdc 0%, #f8f0e0 48%, #efe2cf 100%);
  }

  .face::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(to right, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0) 18%, rgba(0,0,0,0) 82%, rgba(0,0,0,0.18) 100%);
    opacity: 0;
    transition: opacity 0.4s;
    pointer-events: none;
  }

  .sheet.flipped .face-front::after { opacity: 1; }
  .sheet.turning .face::after { opacity: 0.72; }

  .gutter-shadow {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 42px;
    left: calc(50% - 21px);
    background: linear-gradient(90deg, transparent, rgba(0,0,0,0.28) 50%, transparent);
    transform: translateZ(6px);
    border-radius: 50%;
    pointer-events: none;
  }

  .edge-hit-area {
    position: absolute;
    top: 0;
    bottom: 0;
    width: var(--edge-hit);
    z-index: 45;
    pointer-events: auto;
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
  }

  .edge-hit-area--right {
    right: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,236,204,0.02) 45%, rgba(255,236,204,0.10) 100%);
  }

  .edge-hit-area--left {
    left: 0;
    background: linear-gradient(90deg, rgba(255,236,204,0.10) 0%, rgba(255,236,204,0.02) 55%, transparent 100%);
  }

  .edge-hit-area::after {
    content: '';
    position: absolute;
    top: 28px;
    width: 22px;
    height: 22px;
    background: rgba(255, 246, 227, 0.42);
    opacity: 0;
    transition: opacity 0.18s ease, transform 0.18s ease;
    box-shadow: 0 2px 6px rgba(0,0,0,0.10);
  }

  .edge-hit-area--right::after {
    right: 0;
    clip-path: polygon(100% 0, 0 50%, 100% 100%);
    transform: translateX(6px);
  }

  .edge-hit-area--left::after {
    left: 0;
    clip-path: polygon(0 0, 100% 50%, 0 100%);
    transform: translateX(-6px);
  }

  .edge-hit-area:hover::after { opacity: 1; transform: translateX(0); }

  .font-serif-elegant { font-family: 'Playfair Display', serif; }
  .font-script { font-family: 'Dancing Script', cursive; }
  .font-sans-clean { font-family: 'Inter', sans-serif; }

  @keyframes float {
    0% { transform: translateY(0px) rotate(0deg); }
    50% { transform: translateY(-10px) rotate(2deg); }
    100% { transform: translateY(0px) rotate(0deg); }
  }

  .animate-float { animation: float 7s ease-in-out infinite; }

  .page-content {
    width: 100%;
    height: 100%;
    position: relative;
    padding: 18px;
    color: var(--page-ink);
  }

  .page-watermark {
    position: absolute;
    right: 22px;
    top: 14px;
    font-size: 54px;
    font-family: 'Playfair Display', serif;
    opacity: 0.06;
    pointer-events: none;
  }

  .page-layout {
    position: absolute;
    inset: clamp(14px, 3%, 22px) clamp(19px, 4%, 29px) clamp(46px, 8%, 57px);
    display: flex;
    flex-direction: column;
    gap: clamp(12px, 3%, 21px);
    min-height: 0;
  }
  .photo-zone {
    flex: 1.65 1 0;
    width: 100%;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .note-zone {
    flex: 1 1 0;
    width: 100%;
    min-height: 0;
    display: flex;
    align-items: stretch;
    justify-content: center;
  }
  .page-layout.note-first .note-zone { order: -1; }
  .memory-frame {
    position: relative;
    width: 78%;
    max-width: 410px;
    height: 94%;
    min-height: 0;
    cursor: pointer;
    z-index: 5;
    display: flex;
    flex-direction: column;
    transform-origin: center center;
  }
  .memory-frame img,
  .memory-frame .photo-placeholder {
    width: 100%;
    height: calc(100% - 25px);
    min-height: 0;
    object-fit: cover;
    display: block;
    flex: 1 1 auto;
  }
  .frame-polaroid {
    background: #fff;
    padding: 10px 10px 32px;
    border-radius: 3px;
    border: 1px solid rgba(99, 79, 56, 0.12);
    box-shadow: 0 14px 22px rgba(0,0,0,0.18);
  }

  .frame-vintage {
    background: linear-gradient(180deg, #fefaf2 0%, #f4ead9 100%);
    padding: 14px;
    border-radius: 8px;
    border: 1px solid rgba(134, 99, 57, 0.22);
    box-shadow: 0 16px 30px rgba(0,0,0,0.14), inset 0 0 0 2px rgba(204,170,123,0.26);
  }

  .frame-gold {
    background: linear-gradient(180deg, #fffdf9, #f1e6d2);
    padding: 10px;
    border: 4px double #ccab63;
    border-radius: 6px;
    box-shadow: 0 16px 28px rgba(0,0,0,0.15);
  }

  .frame-scrapbook {
    background: #fff;
    padding: 11px;
    border-radius: 2px;
    border: 1px solid rgba(99, 79, 56, 0.12);
    box-shadow: 0 15px 24px rgba(0,0,0,0.14);
  }

  .frame-soft {
    background: linear-gradient(180deg, #fff, #f8efe3);
    padding: 12px;
    border-radius: 14px;
    border: 1px solid rgba(99, 79, 56, 0.10);
    box-shadow: 0 16px 32px rgba(0,0,0,0.15);
  }

  .frame-caption {
    text-align: center;
    margin-top: 8px;
    font-size: 11px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #8f7156;
  }

  .tape {
    position: absolute;
    width: 52px;
    height: 15px;
    background: rgba(242, 225, 178, 0.72);
    border: 1px solid rgba(201, 185, 144, 0.45);
    box-shadow: 0 2px 4px rgba(0,0,0,0.07);
    pointer-events: none;
  }
  .tape--top-left { left: -14px; top: -8px; transform: rotate(-16deg); }
  .tape--top-right { right: -12px; top: -7px; transform: rotate(15deg); }
  .tape--bottom-left { left: -10px; bottom: 16px; transform: rotate(12deg); }

  .photo-placeholder {
    background: linear-gradient(180deg, #fbf7ef, #f2e9da);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #b5a693;
    border: 2px dashed #d7cbb8;
    transition: background 0.16s ease;
  }
  .memory-frame:hover .photo-placeholder { background: #f8f3ea; }

  .memory-note {
    position: relative;
    width: 76%;
    max-width: 92%;
    height: 100%;
    min-height: 0;
    padding: clamp(9px, 2.3%, 16px);
    background: rgba(255,251,242,0.88);
    border: 1px solid rgba(153,123,84,0.18);
    box-shadow: 0 10px 23px rgba(0,0,0,0.09);
    border-radius: 15px 15px 15px 4px;
    box-sizing: border-box;
    transform-origin: center center;
    z-index: 8;
  }
  .memory-note textarea {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 100%;
    min-height: 0;
    box-sizing: border-box;
    border: none;
    background: transparent;
    resize: none;
    overflow-y: auto;
    outline: none;
    font-family: 'Dancing Script', cursive;
    font-size: clamp(1.15rem, calc(var(--book-width) * 0.057), 1.85rem);
    line-height: 1.16;
    color: #5a4030;
  }
  .page-add-btn {
    position: absolute;
    bottom: 18px;
    right: 18px;
    width: 42px;
    height: 42px;
    border-radius: 999px;
    border: 0;
    background: linear-gradient(180deg, var(--cover-warm), var(--cover-color));
    color: #f7df9b;
    box-shadow: 0 10px 16px rgba(0,0,0,0.18);
    font-size: 1.6rem;
    cursor: pointer;
    transition: transform 0.16s ease;
    z-index: 12;
    opacity: 0;
  }

  .page-content:hover .page-add-btn { opacity: 1; }
  .page-add-btn:hover { transform: scale(1.07); }

  .page-index-badge {
    position: absolute;
    left: 18px;
    bottom: 14px;
    font-size: 11px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: rgba(91,63,39,0.52);
  }

  .page-hint {
    position: absolute;
    bottom: 2rem;
    left: 50%;
    transform: translateX(-50%);
    color: rgba(255,255,255,0.58);
    font-size: 12px;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    text-align: center;
    pointer-events: none;
    padding: 0 14px;
  }

  .cover-badge {
    position: absolute;
    top: 18px;
    right: 18px;
    padding: 6px 10px;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 999px;
    font-size: 10px;
    letter-spacing: 0.24em;
    color: rgba(255,239,195,0.78);
    background: rgba(255,255,255,0.06);
    backdrop-filter: blur(2px);
  }

  @media (max-width: 900px) and (orientation: portrait) {
    .page-layout { inset: 15px 17px 46px; gap: 30px; }
    .photo-zone { flex: 1.6 1 0; }
    .note-zone { flex: 1 1 0; }
    .memory-frame { height: 100%; max-width: 84%; }
    .memory-frame img, .memory-frame .photo-placeholder { height: calc(100% - 23px); }
    .memory-note { width: 90% !important; max-width: 94%; padding: 9px 11px; }
    .memory-note textarea { font-size: clamp(1.13rem, 4.4vw, 1.45rem); min-height: 0; }
    .page-content { padding: 10px; }
    .page-add-btn { opacity: 1; width: 36px; height: 36px; bottom: 9px; right: 9px; }
    .page-hint { bottom: 12px; font-size: 10px; width: 94%; line-height: 1.4; }
    .index-page { padding: 22px !important; }
    .index-page h1 { font-size: 1.75rem !important; margin-top: 14px !important; margin-bottom: 26px !important; }
    .index-page ul { font-size: 1rem !important; gap: 16px !important; padding: 0 !important; }
    .cover-page h1 { font-size: 3rem !important; }
  }
  @media (prefers-reduced-motion: reduce) {
    .sheet, .book-container, .edge-hit-area::after { transition-duration: 0.12s !important; animation: none !important; }
  }
`;

type FrameStyle = 'polaroid' | 'vintage' | 'gold' | 'scrapbook' | 'soft';
type TextPlacement =
  | 'top-left'
  | 'top-center'
  | 'top-right'
  | 'middle-left'
  | 'middle-right'
  | 'bottom-left'
  | 'bottom-center'
  | 'bottom-right';

type PageData = {
  type: 'cover' | 'index' | 'editable';
  title?: string;
  subtitle?: string;
  date?: string;
  items?: Array<{ label: string; page: string }>;
  rotation?: number;
  align?: 'flex-start' | 'center' | 'flex-end';
  marginTop?: string;
  imageUrl?: string;
  text?: string;
  frameStyle?: FrameStyle;
  textPlacement?: TextPlacement;
  textRotation?: number;
  textWidth?: string;
  pageAccent?: string;
  pageNumber?: number;
};

type AlbumSheet = { id: string; front: PageData; back: PageData };
type EditablePageProps = { data: PageData; onUpdate: (page: PageData) => void; onAddPage: () => void };
type BookProps = {
  sheets: AlbumSheet[];
  isBookOpen: boolean;
  onOpenBook: () => void;
  onCloseBook: () => void;
  onUpdateSheet: (index: number, face: 'front' | 'back', page: PageData) => void;
  onAddPage: () => void;
  onEnsureNextSheet: () => void;
};

const frameStyles: FrameStyle[] = ['polaroid', 'vintage', 'gold', 'scrapbook', 'soft'];
const textPlacements: TextPlacement[] = ['top-left', 'top-center', 'top-right', 'middle-left', 'middle-right', 'bottom-left', 'bottom-center', 'bottom-right'];
const accents = ['#b88453', '#8b5962', '#6f7b5b', '#9b6d4c', '#4b7d88', '#936255'];
const sampleTexts = [
  'Lembranças que aquecem o coração.',
  'Esse momento merece ficar guardado para sempre.',
  'Uma página nova, uma memória viva.',
  'Teu sorriso transformou esse instante em lembrança.',
  'Entre fotos e palavras, nossa história continua.'
];

const pick = <T,>(array: T[]) => array[Math.floor(Math.random() * array.length)];
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const createRandomEditablePage = (pageNumber?: number): PageData => ({
  type: 'editable',
  rotation: Math.random() * 6 - 3,
  align: (['flex-start', 'center', 'flex-end'] as const)[Math.floor(Math.random() * 3)],
  marginTop: '0px',
  frameStyle: pick(frameStyles),
  textPlacement: pick(textPlacements),
  textRotation: Math.random() * 2.4 - 1.2,
  textWidth: `${Math.floor(Math.random() * 17 + 70)}%`,
  pageAccent: pick(accents),
  pageNumber,
  text: sampleTexts[Math.floor(Math.random() * sampleTexts.length)]
});

const defaultAlbumData: AlbumSheet[] = [
  {
    id: 'sheet-1',
    front: {
      type: 'cover',
      title: 'Nossa História',
      subtitle: 'Memórias',
      date: 'Criado com amor'
    },
    back: {
      type: 'index',
      title: 'Sumário',
      items: [
        { label: 'Como tudo começou...', page: '1' },
        { label: 'Nossas Aventuras', page: '2' },
        { label: 'Momentos Inesquecíveis', page: '5' },
        { label: 'O que ainda está por vir', page: '8' }
      ]
    }
  },
  {
    id: 'sheet-2',
    front: createRandomEditablePage(1),
    back: createRandomEditablePage(2)
  },
  {
    id: 'sheet-3',
    front: createRandomEditablePage(3),
    back: createRandomEditablePage(4)
  },
  {
    id: 'sheet-4',
    front: createRandomEditablePage(5),
    back: createRandomEditablePage(6)
  },
  {
    id: 'sheet-5',
    front: createRandomEditablePage(7),
    back: createRandomEditablePage(8)
  },
  {
    id: 'sheet-6',
    front: createRandomEditablePage(9),
    back: createRandomEditablePage(10)
  }
];

const getFrameClassName = (style?: FrameStyle) => {
  switch (style) {
    case 'vintage': return 'frame-vintage';
    case 'gold': return 'frame-gold';
    case 'scrapbook': return 'frame-scrapbook';
    case 'soft': return 'frame-soft';
    case 'polaroid':
    default: return 'frame-polaroid';
  }
};

const getTextBoxStyle = (width = '77%', rotation = 0, accent = '#8b5962'): React.CSSProperties => ({
  width,
  borderTop: `4px solid ${accent}`,
  transform: `rotate(${rotation}deg)`
});
const getHorizontalPosition = (placement?: string): React.CSSProperties['justifyContent'] => {
  if (placement?.endsWith('left')) return 'flex-start';
  if (placement?.endsWith('right')) return 'flex-end';
  return 'center';
};

const CoverPage = ({ data }: { data: PageData }) => (
  <div className="cover-page w-full h-full flex flex-col items-center justify-center p-8 text-center relative text-white">
    <div className="cover-badge">álbum vivo</div>
    <div className="cover-shine" aria-hidden="true" />
    <div className="absolute inset-0 border-4 border-[var(--gold)] m-4 opacity-50 rounded-sm pointer-events-none" style={{ borderStyle: 'double' }} />
    <h3 className="font-sans-clean text-xs tracking-[0.34em] uppercase text-[var(--gold)] mb-4">O Álbum de</h3>
    <h1 className="font-serif-elegant text-5xl md:text-6xl text-[var(--gold)] mb-6">{data.title || 'Título'}</h1>
    <div className="w-16 h-[1px] bg-[var(--gold)] mb-6" />
    <h2 className="font-script text-4xl text-white mb-8">{data.subtitle || 'Subtítulo'}</h2>
    <p className="font-sans-clean text-sm tracking-widest text-gray-300 absolute bottom-12">{data.date}</p>
    <div className="absolute bottom-24 w-16 h-16 bg-red-700 rounded-full flex items-center justify-center shadow-lg shadow-black/50 border-2 border-red-900">
      <span className="font-serif-elegant text-gold-200 text-sm">EA</span>
    </div>
  </div>
);

const IndexPage = ({ data }: { data: PageData }) => (
  <div className="index-page w-full h-full p-12 bg-[#fcf9f2] flex flex-col relative text-[var(--cover-color)]">
    <span className="page-watermark">01</span>
    <h1 className="font-serif-elegant text-4xl mb-10 text-center border-b-2 border-[var(--gold)] pb-4 mt-8">
      {data.title || 'Sumário'}
    </h1>
    <ul className="flex flex-col gap-6 font-sans-clean text-lg px-4">
      {data.items?.map((item, i) => (
        <li key={i} className="flex justify-between items-end border-b border-gray-300 border-dotted pb-1 hover:text-[var(--gold)] transition-colors cursor-pointer">
          <span className="font-serif-elegant italic">{item.label}</span>
          <span className="font-bold font-sans-clean text-[var(--gold)]">{item.page}</span>
        </li>
      ))}
    </ul>
    <div className="absolute bottom-8 left-0 right-0 text-center">
      <div className="w-12 h-[1px] bg-[var(--gold)] mx-auto mb-2 opacity-50" />
      <p className="font-script text-xl text-gray-500">Nossos capítulos</p>
    </div>
  </div>
);

const EditablePage = ({ data, onUpdate, onAddPage }: EditablePageProps) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const frameClass = getFrameClassName(data.frameStyle);
  const noteStyle = useMemo(
    () => getTextBoxStyle(data.textWidth, data.textRotation, data.pageAccent),
    [data.textWidth, data.textRotation, data.pageAccent]
  );

  const handleImageClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files[0];
    if (file) {
      const url = URL.createObjectURL(file);
      onUpdate({ ...data, imageUrl: url });
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onUpdate({ ...data, text: e.target.value });
  };

  return (
    <div className="page-content group" style={{ ['--page-accent' as string]: data.pageAccent || '#8b5962' }}>
      <span className="page-watermark">{String(data.pageNumber || '').padStart(2, '0')}</span>

      <div className={`page-layout ${data.textPlacement?.startsWith('top') || data.textPlacement === 'middle-left' ? 'note-first' : ''}`}>
        <div className="photo-zone" style={{ justifyContent: data.align === 'flex-start' ? 'flex-start' : data.align === 'flex-end' ? 'flex-end' : 'center' }}>
          <div
            className={`memory-frame ${frameClass}`}
            style={{ transform: `rotate(${data.rotation || 0}deg)` }}
            onClick={handleImageClick}
            role="button"
            tabIndex={0}
            aria-label="Adicionar ou substituir fotografia"
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            {data.frameStyle === 'scrapbook' && <span className="tape tape--top-left" />}
            {data.frameStyle === 'scrapbook' && <span className="tape tape--top-right" />}
            {data.frameStyle === 'soft' && <span className="tape tape--bottom-left" />}
            {data.imageUrl ? <img src={data.imageUrl} alt="Memória" /> : (
              <div className="photo-placeholder">
                <span className="text-3xl mb-2">+</span>
                <span className="font-sans-clean text-sm">Adicionar foto</span>
              </div>
            )}
            <input type="file" className="hidden" ref={fileInputRef} onChange={handleFileChange} accept="image/*" />
            <div className="frame-caption">Clique para trocar a foto</div>
          </div>
        </div>
        <div className="note-zone" style={{ justifyContent: getHorizontalPosition(data.textPlacement) }}>
          <div className="memory-note" style={noteStyle} onClick={(e) => e.stopPropagation()}>
            <textarea
              aria-label="Escreva uma memória"
              placeholder="Escreva sua memória aqui..."
              value={data.text || ''}
              onChange={handleTextChange}
            />
          </div>
        </div>
      </div>

      <button
        className="page-add-btn"
        onClick={(e) => {
          e.stopPropagation();
          onAddPage();
        }}
        title="Adicionar nova folha"
      >
        +
      </button>

      <div className="page-index-badge">folha personalizada</div>
    </div>
  );
};

const RenderPageContent = ({ data, onUpdate, onAddPage }: EditablePageProps) => {
  if (!data) return null;

  switch (data.type) {
    case 'cover':
      return <CoverPage data={data} />;
    case 'index':
      return <IndexPage data={data} />;
    case 'editable':
      return <EditablePage data={data} onUpdate={onUpdate} onAddPage={onAddPage} />;
    default:
      return <div className="w-full h-full bg-[#fcf9f2]" />;
  }
};

const Book = ({ sheets, isBookOpen, onOpenBook, onCloseBook, onUpdateSheet, onAddPage, onEnsureNextSheet }: BookProps) => {
  const [currentSheetIndex, setCurrentSheetIndex] = useState(0);
  const [turningSheetIndex, setTurningSheetIndex] = useState<number | null>(null);
  const [isMobilePortrait, setIsMobilePortrait] = useState(false);
  const [mobileSide, setMobileSide] = useState<'left' | 'right'>('left');
  useEffect(() => {
    const media = window.matchMedia('(max-width: 900px) and (orientation: portrait)');
    const updateMedia = () => setIsMobilePortrait(media.matches);
    updateMedia();
    media.addEventListener('change', updateMedia);
    return () => media.removeEventListener('change', updateMedia);
  }, []);

  const animationLocked = useRef(false);
  const releaseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openingFocusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const swipeStartX = useRef<number | null>(null);

  const unlock = () => {
    animationLocked.current = false;
    setTurningSheetIndex(null);
    if (releaseTimer.current !== null) {
      clearTimeout(releaseTimer.current);
      releaseTimer.current = null;
    }
  };

  useEffect(() => () => {
    if (releaseTimer.current !== null) clearTimeout(releaseTimer.current);
    if (openingTimer.current !== null) clearTimeout(openingTimer.current);
    if (closingTimer.current !== null) clearTimeout(closingTimer.current);
    if (openingFocusTimer.current !== null) clearTimeout(openingFocusTimer.current);
  }, []);

  const turnSheet = (sheetIndex: number, nextIndex: number) => {
    if (animationLocked.current) return;
    animationLocked.current = true;
    setTurningSheetIndex(sheetIndex);
    setCurrentSheetIndex(nextIndex);
    releaseTimer.current = setTimeout(unlock, 1250);
  };

  const flipNext = () => {
    if (animationLocked.current) return;

    if (!isBookOpen) {
      animationLocked.current = true;
      onOpenBook();
      // Mantém a capa visível durante a abertura; só depois enquadra a página esquerda.
      setMobileSide('right');
      openingTimer.current = setTimeout(() => {
        openingTimer.current = null;
        animationLocked.current = false;
        turnSheet(0, 1);
        if (isMobilePortrait) {
          openingFocusTimer.current = setTimeout(() => {
            setMobileSide('left');
            openingFocusTimer.current = null;
          }, 1120);
        }
      }, 860);
      return;
    }

    // Em celulares retrato: a primeira ação mostra a página à direita;
    // a seguinte folheia e revela o verso à esquerda.
    if (isMobilePortrait && mobileSide === 'left') {
      setMobileSide('right');
      return;
    }
    if (currentSheetIndex === sheets.length - 1) onEnsureNextSheet();
    if (currentSheetIndex < sheets.length) {
      turnSheet(currentSheetIndex, currentSheetIndex + 1);
      if (isMobilePortrait) setMobileSide('left');
    }
  };

  const flipPrev = () => {
    if (!isBookOpen || animationLocked.current || currentSheetIndex === 0) return;
    if (isMobilePortrait && mobileSide === 'right') {
      setMobileSide('left');
      return;
    }
    const previous = currentSheetIndex - 1;
    turnSheet(previous, previous);
    if (isMobilePortrait) setMobileSide('right');
    if (previous === 0) {
      closingTimer.current = setTimeout(() => {
        onCloseBook();
        setMobileSide('left');
        closingTimer.current = null;
      }, 1140);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest('textarea, input, button, [contenteditable="true"]')) return;
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        flipNext();
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        flipPrev();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  const sheetStep = Math.min(2.2, 20 / Math.max(1, sheets.length));
  const leftCount = currentSheetIndex;
  const rightCount = Math.max(1, sheets.length - currentSheetIndex);
  const leftStackThickness = clamp(8 + leftCount * sheetStep * 5, 8, 36);
  const rightStackThickness = clamp(8 + rightCount * sheetStep * 5, 12, 44);

  return (
    <>
    <div
      className={`book-shell ${isBookOpen ? 'is-open' : ''}`}
      onTouchStart={(event) => {
        const el = event.target;
        if (el instanceof HTMLElement && el.closest('input, textarea, button, .memory-frame')) {
          swipeStartX.current = null;
          return;
        }
        swipeStartX.current = event.touches[0]?.clientX ?? null;
      }}
      onTouchEnd={(event) => {
        if (!isMobilePortrait || swipeStartX.current === null || !isBookOpen) return;
        const delta = event.changedTouches[0]?.clientX - swipeStartX.current;
        swipeStartX.current = null;
        if (delta < -52) flipNext();
        if (delta > 52) flipPrev();
      }}
    >
      <div className="book-ground-shadow" aria-hidden="true" />
      <div className={`book-container ${isBookOpen ? 'open' : 'closed'} ${isMobilePortrait ? `mobile-portrait mobile-focus-${mobileSide}` : ''}`} onClick={!isBookOpen ? flipNext : undefined}>
        <div className="book-hardcover-back" aria-hidden="true" />
        <div className="book-spine" aria-hidden="true" />
        <div className="gutter-shadow" aria-hidden="true" />
        {/* Pilha esquerda só aparece quando a folha terminou a animação. */}
        {leftCount > 0 && turningSheetIndex === null && (
          <div className="page-stack page-stack-left" aria-hidden="true" style={{ ['--stack-thickness' as string]: `${leftStackThickness}px`, opacity: Math.min(0.95, 0.35 + leftCount / Math.max(1, sheets.length)) }} />
        )}
        <div className="page-stack page-stack-right" aria-hidden="true" style={{ ['--stack-thickness' as string]: `${rightStackThickness}px`, opacity: Math.min(0.98, 0.4 + rightCount / Math.max(1, sheets.length)) }} />

        {sheets.map((sheet, idx) => {
          const isFlipped = idx < currentSheetIndex;
          const isTurning = turningSheetIndex === idx;
          const canClickRight = idx === currentSheetIndex;
          const canClickLeft = isBookOpen && idx === currentSheetIndex - 1;
          const zIndex = isTurning ? 500 : (isFlipped ? idx + 1 : sheets.length - idx);
          const depth = isFlipped ? (idx + 1) * sheetStep : (sheets.length - idx) * sheetStep;

          return (
            <div
              key={sheet.id}
              className={`sheet ${isFlipped ? 'flipped' : ''} ${isTurning ? 'turning' : ''} ${idx === 0 ? 'is-cover' : ''}`}
              style={{
                zIndex,
                transform: `translateZ(${depth}px) rotateY(${isFlipped ? -180 : 0}deg)`
              }}
              onTransitionEnd={(event) => {
                if (event.target === event.currentTarget && event.propertyName === 'transform' && isTurning) unlock();
              }}
            >
              <div className={`face face-front ${canClickRight ? 'interactive' : ''}`}>
                <RenderPageContent
                  data={sheet.front}
                  onUpdate={(newData) => onUpdateSheet(idx, 'front', newData)}
                  onAddPage={onAddPage}
                />
                {isBookOpen && canClickRight && (
                  <button
                    type="button"
                    className="edge-hit-area edge-hit-area--right"
                    aria-label="Ir para as próximas páginas"
                    title="Clique na ponta do livro para avançar"
                    onClick={(event) => {
                      event.stopPropagation();
                      flipNext();
                    }}
                  />
                )}
              </div>

              <div className={`face face-back ${canClickLeft ? 'interactive' : ''}`}>
                <RenderPageContent
                  data={sheet.back}
                  onUpdate={(newData) => onUpdateSheet(idx, 'back', newData)}
                  onAddPage={onAddPage}
                />
                {canClickLeft && (
                  <button
                    type="button"
                    className="edge-hit-area edge-hit-area--left"
                    aria-label="Voltar para as páginas anteriores"
                    title="Clique na ponta do livro para voltar"
                    onClick={(event) => {
                      event.stopPropagation();
                      flipPrev();
                    }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
    {isBookOpen && isMobilePortrait && (
      <>
        <button className="mobile-nav-zone mobile-nav-zone--left" type="button" aria-label="Página anterior" onClick={flipPrev} />
        <button className="mobile-nav-zone mobile-nav-zone--right" type="button" aria-label="Próxima página" onClick={flipNext} />
      </>
    )}
    </>
  );
};

export default function App() {
  const [albumData, setAlbumData] = useState(defaultAlbumData);
  const [isBookOpen, setIsBookOpen] = useState(false);
  const [showPrompt, setShowPrompt] = useState(true);
  const particles = useMemo(() => Array.from({ length: 18 }, (_, i) => ({
    key: i, size: Math.random() * 5 + 2, top: Math.random() * 100, left: Math.random() * 100,
    duration: Math.random() * 5 + 5, delay: Math.random() * 5
  })), []);
  const pageCounter = useRef(11);

  const handleOpenBook = () => {
    setIsBookOpen(true);
    setShowPrompt(false);
  };

  const handleCloseBook = () => {
    setIsBookOpen(false);
    setShowPrompt(true);
  };

  const handleUpdateSheet = (sheetIndex: number, face: 'front' | 'back', newData: PageData) => {
    setAlbumData((prev) => prev.map((sheet, idx) => (idx === sheetIndex ? { ...sheet, [face]: newData } : sheet)));
  };

  const createSheet = (): AlbumSheet => {
    const frontNumber = pageCounter.current++;
    const backNumber = pageCounter.current++;
    return {
      id: `sheet-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      front: createRandomEditablePage(frontNumber),
      back: createRandomEditablePage(backNumber)
    };
  };

  const handleAddPage = () => {
    setAlbumData((prev) => [...prev, createSheet()]);
  };

  return (
    <>
      <style>{globalStyles}</style>
      <div className="scene relative font-sans-clean">

        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          {particles.map((particle) => (
            <div
              key={particle.key}
              className="absolute bg-white/10 rounded-full animate-float"
              style={{
                width: particle.size + 'px', height: particle.size + 'px',
                top: particle.top + '%', left: particle.left + '%',
                animationDuration: particle.duration + 's', animationDelay: particle.delay + 's'
              }}
            />
          ))}
        </div>

        <Book
          sheets={albumData}
          isBookOpen={isBookOpen}
          onOpenBook={handleOpenBook}
          onCloseBook={handleCloseBook}
          onUpdateSheet={handleUpdateSheet}
          onAddPage={handleAddPage}
          onEnsureNextSheet={handleAddPage}
        />

        {showPrompt && !isBookOpen && (
          <div className="absolute bottom-20 flex flex-col items-center animate-bounce pointer-events-none">
            <p className="text-[var(--gold)] font-serif-elegant text-xl tracking-widest mb-2 shadow-black drop-shadow-md">
              Clique para abrir
            </p>
            <div className="w-6 h-6 border-b-2 border-r-2 border-[var(--gold)] rotate-45 opacity-70" />
          </div>
        )}

        {isBookOpen && (
          <div className="page-hint">
            Toque na ponta direita para avançar · ponta esquerda para voltar · + adiciona uma folha
          </div>
        )}
      </div>
    </>
  );
}
