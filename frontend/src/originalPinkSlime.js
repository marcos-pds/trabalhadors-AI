import * as THREE from 'three'

// Faithful adaptation of the user's original "avatares_3d_interativos 3.html".
// Pink Slime's mesh, expression system, eyes, blink, yawn, drag, jelly
// dynamics and facial details are preserved. Only browser-page DOM bindings
// and the standalone scene/bootstrap were removed.
const SLIME_MODELS = [
            {
                id: 'pink',
                label: 'Pink Slime',
                topColor: '#ffa6c1',    // Rosa pastel iluminado no topo da cúpula
                midColor: '#f2577b',    // Rosa vibrante principal do corpo
                baseColor: '#be1e45',   // Rosa-framboesa profundo na base arredondada
                sheenColor: '#ffc2d4',
                eyeTop: '#240b08',      // Castanho expresso escuro no topo do olho
                eyeBottom: '#8f3914',   // Castanho âmbar quente na base do olho
                mouthColor: 0x3b1116,   // Marrom-vinho escuro da boquinha
                blushColor: 0xff2a6d,
                glowHex: '#f45d7f',
                accessory: 'none'
            },
            {
                id: 'honey',
                label: 'Honey Slime',
                topColor: '#fde68a',
                midColor: '#f59e0b',
                baseColor: '#b45309',
                sheenColor: '#fef3c7',
                eyeTop: '#291205',
                eyeBottom: '#9a4608',
                mouthColor: 0x3d1906,
                blushColor: 0xff6b35,
                glowHex: '#f59e0b',
                accessory: 'crown-drop'
            },
            {
                id: 'neko',
                label: 'Neko Slime',
                topColor: '#f5d0fe',
                midColor: '#c084fc',
                baseColor: '#7e22ce',
                sheenColor: '#fae8ff',
                eyeTop: '#1e0b2b',
                eyeBottom: '#6b21a8',
                mouthColor: 0x2e1042,
                blushColor: 0xf43f5e,
                glowHex: '#c084fc',
                accessory: 'cat-ears'
            },
            {
                id: 'aqua',
                label: 'Aqua Slime',
                topColor: '#a5f3fc',
                midColor: '#06b6d4',
                baseColor: '#0369a1',
                sheenColor: '#cffafe',
                eyeTop: '#082032',
                eyeBottom: '#0284c7',
                mouthColor: 0x0c2d48,
                blushColor: 0x38bdf8,
                glowHex: '#06b6d4',
                accessory: 'bubbles'
            }
        ];

        // ---------------------------------------------------------

function createContactShadowTexture() {
            const canvas = document.createElement('canvas');
            canvas.width = 256;
            canvas.height = 256;
            const ctx = canvas.getContext('2d');
            const grad = ctx.createRadialGradient(128, 128, 12, 128, 128, 120);
            grad.addColorStop(0, 'rgba(35, 12, 20, 0.42)');
            grad.addColorStop(0.55, 'rgba(35, 12, 20, 0.16)');
            grad.addColorStop(1, 'rgba(35, 12, 20, 0)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 256, 256);
            return new THREE.CanvasTexture(canvas);
        }

        // Textura dos Olhos Castanhos com Reflexo Branco Superior Interno (Idêntico à referência)
        function createSlimeEyeTexture(topHex, bottomHex, side) {
            const canvas = document.createElement('canvas');
            canvas.width = 256;
            canvas.height = 256;
            const ctx = canvas.getContext('2d');

            // Degradê vertical castanho-expresso no topo para âmbar-castanho embaixo
            const grad = ctx.createLinearGradient(0, 20, 0, 236);
            grad.addColorStop(0, topHex);
            grad.addColorStop(0.52, topHex);
            grad.addColorStop(1, bottomHex);
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 256, 256);

            // Sombra interna sutil na borda superior
            const rimGrad = ctx.createRadialGradient(128, 145, 30, 128, 128, 128);
            rimGrad.addColorStop(0, 'rgba(255, 255, 255, 0)');
            rimGrad.addColorStop(1, 'rgba(15, 4, 2, 0.45)');
            ctx.fillStyle = rimGrad;
            ctx.fillRect(0, 0, 256, 256);

            // Reflexo especular branco oval nítido na parte superior-interna (fiel à imagem)
            ctx.save();
            const specX = side === -1 ? 142 : 114; // Levemente voltado para o centro do rosto
            const specY = 82;
            ctx.translate(specX, specY);
            ctx.rotate(side === -1 ? -0.15 : 0.15);
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.ellipse(0, 0, 30, 38, 0, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();

            const tex = new THREE.CanvasTexture(canvas);
            tex.colorSpace = THREE.SRGBColorSpace;
            return tex;
        }

        // ---------------------------------------------------------
        // 3. FUNÇÃO MATEMÁTICA DA SILHUETA DO SLIME (MOCHI / GUMDROP DOME)
        // ---------------------------------------------------------
        // Converte qualquer coordenada de esfera unitária (nx, ny, nz) para a superfície exata do Slime da imagem
        function evalSlimeSurface(nx, ny, nz) {
            const u = ny; // [-1 no polo sul, +1 no polo norte]

            // Achatamento suave da base para assentar no chão com borda inferior arredondada
            let y;
            if (u < -0.55) {
                const t = (u + 0.55) / 0.45; // [0 a -1]
                y = -0.55 + 0.27 * Math.sin(t * Math.PI * 0.5); // Base suave em y = -0.82
            } else {
                y = u * 0.94;
            }

            // Expansão gordinha na barriga inferior (u em torno de -0.28) e cúpula redonda no topo
            const bellyBulge = 1.0 + 0.15 * Math.exp(-Math.pow((u + 0.26) / 0.48, 2));
            const topTaper = u > 0 ? (1.0 - 0.05 * Math.pow(u, 1.6)) : 1.0;
            const bottomCurve = u < -0.62 ? (1.0 - 0.16 * Math.pow((-0.62 - u) / 0.38, 1.8)) : 1.0;

            const horizScale = bellyBulge * topTaper * bottomCurve * 1.06;
            return new THREE.Vector3(nx * horizScale, y, nz * horizScale);
        }

        // ---------------------------------------------------------
        // 4. CLASSE PRINCIPAL DO SLIME 3D INTERATIVO
        // ---------------------------------------------------------
        class PinkSlimeAvatar {
            constructor(scene) {
                this.root = new THREE.Group();
                scene.add(this.root);

                // Sombra de contato no chão
                const shadowGeo = new THREE.PlaneGeometry(2.55, 2.55);
                const shadowMat = new THREE.MeshBasicMaterial({
                    map: createContactShadowTexture(),
                    transparent: true,
                    depthWrite: false
                });
                this.shadowMesh = new THREE.Mesh(shadowGeo, shadowMat);
                this.shadowMesh.rotation.x = -Math.PI / 2;
                this.shadowMesh.position.y = -0.83;
                this.root.add(this.shadowMesh);

                // Grupo principal que gira (Turnaround 360°) e pula
                this.slimeGroup = new THREE.Group();
                this.root.add(this.slimeGroup);

                // Estado de Física Soft-Body (Squash & Stretch + Gelatina)
                this.scaleSpring = new THREE.Vector3(1, 1, 1);
                this.scaleVel = new THREE.Vector3(0, 0, 0);
                this.dragOffset = new THREE.Vector2(0, 0);
                this.jiggleIntensity = 0;

                // Estado de Expressões e Interações
                this.modelConfig = SLIME_MODELS[0];
                this.expression = 'idle'; // 'idle' | 'happy' | 'yawn' | 'dizzy' | 'love'
                this.expressionTimer = 0;
                this.idleTime = 0;
                this.blinkTimer = 2.6;
                this.isBlinking = false;
                this.isJumping = false;
                this.jumpPhase = 0;
                this.isTyping = false;
                this.isChatOpen = true;

                // Rotação e Olhar
                this.targetRotY = 0; // 0 = FRONT
                this.currentRotY = 0;
                this.currentRotX = 0;
                this.eyeLook = new THREE.Vector2(0, 0);

                this.buildSlimeBody();
                this.buildFacialFeatures();
                this.buildAccessories();
                this. buildParticles();
                this.applyTheme(0);
            }

            buildSlimeBody() {
                // Malha de alta densidade para deformação suave de gelatina e silhueta perfeita
                const geo = new THREE.SphereGeometry(1, 96, 96);
                const pos = geo.attributes.position;
                const vertexCount = pos.count;

                this.basePositions = new Float32Array(vertexCount * 3);
                this.vertexColors = new Float32Array(vertexCount * 3);

                for (let i = 0; i < vertexCount; i++) {
                    const vx = pos.getX(i);
                    const vy = pos.getY(i);
                    const vz = pos.getZ(i);
                    const len = Math.hypot(vx, vy, vz) || 1;
                    const mapped = evalSlimeSurface(vx / len, vy / len, vz / len);

                    pos.setXYZ(i, mapped.x, mapped.y, mapped.z);
                    this.basePositions[i * 3] = mapped.x;
                    this.basePositions[i * 3 + 1] = mapped.y;
                    this.basePositions[i * 3 + 2] = mapped.z;
                }

                geo.setAttribute('color', new THREE.BufferAttribute(this.vertexColors, 3));
                geo.computeVertexNormals();

                this.bodyGeo = geo;
                this.bodyMat = new THREE.MeshPhysicalMaterial({
                    vertexColors: true,
                    roughness: 0.25,
                    metalness: 0.01,
                    clearcoat: 0.42,
                    clearcoatRoughness: 0.28,
                    sheen: 0.75,
                    sheenRoughness: 0.35,
                    sheenColor: new THREE.Color('#ffc2d4')
                });

                this.bodyMesh = new THREE.Mesh(this.bodyGeo, this.bodyMat);
                this.slimeGroup.add(this.bodyMesh);
            }

            updateVertexGradient(topHex, midHex, baseHex) {
                const cTop = new THREE.Color(topHex);
                const cMid = new THREE.Color(midHex);
                const cBase = new THREE.Color(baseHex);
                const temp = new THREE.Color();

                const count = this.bodyGeo.attributes.position.count;
                const colors = this.bodyGeo.attributes.color;

                for (let i = 0; i < count; i++) {
                    const y = this.basePositions[i * 3 + 1];
                    // Normaliza y de [-0.82, +0.94] para [0, 1]
                    const t = THREE.MathUtils.clamp((y + 0.82) / 1.76, 0, 1);
                    if (t < 0.45) {
                        temp.lerpColors(cBase, cMid, t / 0.45);
                    } else {
                        temp.lerpColors(cMid, cTop, (t - 0.45) / 0.55);
                    }
                    colors.setXYZ(i, temp.r, temp.g, temp.b);
                }
                colors.needsUpdate = true;
            }

            buildFacialFeatures() {
                this.faceGroup = new THREE.Group();
                this.slimeGroup.add(this.faceGroup);

                // 1. OLHOS 3D OVAIS (Acompanhando exatamente a curvatura frontal +/- 26.5 graus)
                this.leftEyeMat = new THREE.MeshPhysicalMaterial({
                    roughness: 0.1,
                    metalness: 0.0,
                    clearcoat: 1.0,
                    clearcoatRoughness: 0.06
                });
                this.rightEyeMat = this.leftEyeMat.clone();

                const eyeGeo = new THREE.SphereGeometry(1, 36, 36);
                // Ajusta UV frontal da esfera para mapear a textura do olho perfeitamente na face +Z
                const uv = eyeGeo.attributes.uv;
                const pos = eyeGeo.attributes.position;
                for (let i = 0; i < pos.count; i++) {
                    const x = pos.getX(i);
                    const y = pos.getY(i);
                    uv.setXY(i, x * 0.5 + 0.5, y * 0.5 + 0.5);
                }

                this.leftEyeHolder = new THREE.Group();
                this.rightEyeHolder = new THREE.Group();

                this.leftEyeMesh = new THREE.Mesh(eyeGeo, this.leftEyeMat);
                this.rightEyeMesh = new THREE.Mesh(eyeGeo, this.rightEyeMat);

                // Escala oval idêntica à folha de modelo (mais alto que largo e levemente abaulado)
                this.baseEyeScale = new THREE.Vector3(0.115, 0.158, 0.052);
                this.leftEyeMesh.scale.copy(this.baseEyeScale);
                this.rightEyeMesh.scale.copy(this.baseEyeScale);

                this.leftEyeHolder.add(this.leftEyeMesh);
                this.rightEyeHolder.add(this.rightEyeMesh);
                this.faceGroup.add(this.leftEyeHolder, this.rightEyeHolder);

                // Olhos Felizes em Arco (^ ^) para reação de Clique / Amor
                this.happyEyesGroup = new THREE.Group();
                this.happyEyesGroup.visible = false;
                this.darkFeatureMat = new THREE.MeshStandardMaterial({
                    color: 0x3b1116,
                    roughness: 0.35
                });

                [-1, 1].forEach(side => {
                    const curvePts = [];
                    for (let i = 0; i <= 16; i++) {
                        const t = (i / 16) * Math.PI;
                        const ang = side * 0.45 + Math.cos(t) * 0.11;
                        const elev = -0.04 + Math.sin(t) * 0.09;
                        const nx = Math.sin(ang) * Math.cos(elev);
                        const ny = Math.sin(elev);
                        const nz = Math.cos(ang) * Math.cos(elev);
                        const p = evalSlimeSurface(nx, ny, nz).multiplyScalar(1.012);
                        curvePts.push(p);
                    }
                    const arcCurve = new THREE.CatmullRomCurve3(curvePts);
                    const arcGeo = new THREE.TubeGeometry(arcCurve, 20, 0.026, 12, false);
                    const arcMesh = new THREE.Mesh(arcGeo, this.darkFeatureMat);
                    this.happyEyesGroup.add(arcMesh);
                });
                this.faceGroup.add(this.happyEyesGroup);

                // Bochechas Rosadas Suaves (Aparecem quando feliz / clicado / apaixonado)
                const blushGeo = new THREE.SphereGeometry(1, 24, 24);
                this.blushMat = new THREE.MeshBasicMaterial({
                    color: 0xff2a6d,
                    transparent: true,
                    opacity: 0.0
                });
                this.leftBlush = new THREE.Mesh(blushGeo, this.blushMat);
                this.rightBlush = new THREE.Mesh(blushGeo, this.blushMat);
                [-1, 1].forEach(side => {
                    const mesh = side === -1 ? this.leftBlush : this.rightBlush;
                    const ang = side * 0.58;
                    const elev = -0.16;
                    const p = evalSlimeSurface(Math.sin(ang) * Math.cos(elev), Math.sin(elev), Math.cos(ang) * Math.cos(elev));
                    mesh.position.copy(p).multiplyScalar(1.005);
                    mesh.lookAt(p.clone().multiplyScalar(2));
                    mesh.scale.set(0.12, 0.065, 0.02);
                    this.faceGroup.add(mesh);
                });

                // 2. BOCA SORRIDENTE 3D (Idêntica à referência: tubo escuro curvo com pontas arredondadas)
                const smilePts = [];
                const smileSpan = 0.185;
                for (let i = 0; i <= 20; i++) {
                    const u = (i / 20) * 2 - 1; // [-1 a +1]
                    const lon = u * smileSpan;
                    const lat = -0.165 + (u * u) * 0.048; // Curva de sorriso suave ◡
                    const nx = Math.sin(lon) * Math.cos(lat);
                    const ny = Math.sin(lat);
                    const nz = Math.cos(lon) * Math.cos(lat);
                    const p = evalSlimeSurface(nx, ny, nz).multiplyScalar(1.012);
                    smilePts.push(p);
                }
                const smileCurve = new THREE.CatmullRomCurve3(smilePts);
                const smileRadius = 0.024;
                const smileGeo = new THREE.TubeGeometry(smileCurve, 24, smileRadius, 14, false);

                this.smileGroup = new THREE.Group();
                const smileTube = new THREE.Mesh(smileGeo, this.darkFeatureMat);
                this.smileGroup.add(smileTube);

                // Tampas esféricas nas duas extremidades do sorriso para acabamento arredondado perfeito
                [smilePts[0], smilePts[smilePts.length - 1]].forEach(endPt => {
                    const cap = new THREE.Mesh(new THREE.SphereGeometry(smileRadius, 12, 12), this.darkFeatureMat);
                    cap.position.copy(endPt);
                    this.smileGroup.add(cap);
                });
                this.faceGroup.add(this.smileGroup);

                // 3. BOCA ABERTA 3D (Para Bocejo 🥱, Surpresa ao Arrastar 😵 e Pulo Feliz)
                this.openMouthGroup = new THREE.Group();
                this.openMouthGroup.visible = false;
                const mouthPos = evalSlimeSurface(0, -0.16, 1).multiplyScalar(1.01);
                this.openMouthGroup.position.copy(mouthPos);
                this.openMouthGroup.lookAt(mouthPos.clone().multiplyScalar(2));

                const cavityMesh = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 24), this.darkFeatureMat);
                cavityMesh.scale.set(1.0, 1.15, 0.35);
                this.openMouthGroup.add(cavityMesh);

                const tongueMat = new THREE.MeshBasicMaterial({ color: 0xff758f });
                const tongueMesh = new THREE.Mesh(new THREE.SphereGeometry(0.068, 20, 20), tongueMat);
                tongueMesh.position.set(0, -0.038, 0.018);
                tongueMesh.scale.set(1.1, 0.75, 0.35);
                this.openMouthGroup.add(tongueMesh);

                this.faceGroup.add(this.openMouthGroup);
            }

            buildAccessories() {
                // Orelhinhas 3D para a variante Neko Slime
                this.catEarsGroup = new THREE.Group();
                this.catEarsGroup.visible = false;
                const earGeo = new THREE.ConeGeometry(0.28, 0.48, 32);
                [-1, 1].forEach(side => {
                    const ear = new THREE.Mesh(earGeo, this.bodyMat);
                    ear.position.set(side * 0.55, 0.78, 0.05);
                    ear.rotation.z = -side * 0.42;
                    this.catEarsGroup.add(ear);
                });
                this.slimeGroup.add(this.catEarsGroup);

                // Gotinha / Coroa de Mel para a variante Honey Slime
                this.crownDropGroup = new THREE.Group();
                this.crownDropGroup.visible = false;
                const dropMesh = new THREE.Mesh(new THREE.SphereGeometry(0.14, 24, 24), this.bodyMat);
                dropMesh.scale.set(0.85, 1.35, 0.85);
                dropMesh.position.set(0, 0.98, 0);
                this.crownDropGroup.add(dropMesh);
                this.slimeGroup.add(this.crownDropGroup);
            }

            buildParticles() {
                // Bolhas flutuantes de sono / alegria ao redor do Slime
                this.particlesGroup = new THREE.Group();
                this.root.add(this.particlesGroup);
                this.particles = [];

                const bubbleGeo = new THREE.SphereGeometry(0.06, 16, 16);
                const bubbleMat = new THREE.MeshPhysicalMaterial({
                    color: 0xffffff,
                    transparent: true,
                    opacity: 0.65,
                    roughness: 0.1,
                    clearcoat: 1.0
                });

                for (let i = 0; i < 6; i++) {
                    const mesh = new THREE.Mesh(bubbleGeo, bubbleMat.clone());
                    mesh.visible = false;
                    this.particlesGroup.add(mesh);
                    this.particles.push({
                        mesh,
                        phase: i * 1.1,
                        speed: 0.7 + Math.random() * 0.4,
                        radius: 0.9 + Math.random() * 0.35
                    });
                }
            }

            applyTheme(index) {
                const cfg = SLIME_MODELS[index];
                this.modelConfig = cfg;

                this.updateVertexGradient(cfg.topColor, cfg.midColor, cfg.baseColor);
                this.bodyMat.sheenColor.set(cfg.sheenColor);
                this.darkFeatureMat.color.setHex(cfg.mouthColor);
                this.blushMat.color.setHex(cfg.blushColor);

                this.leftEyeMat.map = createSlimeEyeTexture(cfg.eyeTop, cfg.eyeBottom, -1);
                this.leftEyeMat.needsUpdate = true;
                this.rightEyeMat.map = createSlimeEyeTexture(cfg.eyeTop, cfg.eyeBottom, 1);
                this.rightEyeMat.needsUpdate = true;

                this.catEarsGroup.visible = cfg.accessory === 'cat-ears';
                this.crownDropGroup.visible = cfg.accessory === 'crown-drop';

            }

            triggerSquash(sx, sy, sz, jiggle = 1.0) {
                this.scaleVel.x += (sx - this.scaleSpring.x) * 14;
                this.scaleVel.y += (sy - this.scaleSpring.y) * 14;
                this.scaleVel.z += (sz - this.scaleSpring.z) * 14;
                this.jiggleIntensity = Math.min(1.6, this.jiggleIntensity + jiggle);
            }

            triggerReaction(expr, duration = 2.8) {
                this.expression = expr;
                this.expressionTimer = duration;
                this.idleTime = 0;

                if (expr === 'happy' || expr === 'love') {
                    this.isJumping = true;
                    this.jumpPhase = 0;
                    this.triggerSquash(1.22, 0.78, 1.22, 1.1);
                } else if (expr === 'yawn') {
                    this.triggerSquash(0.88, 1.18, 0.88, 0.5);
                } else if (expr === 'dizzy') {
                    this.triggerSquash(1.28, 0.74, 1.28, 1.5);
                }
            }

            setTurnaroundAngle(rad) {
                this.targetRotY = rad;
            }

            update(dt, time, globalMouse, isDragging) {
                // 1. Temporizador de Expressões e Bocejo Automático quando parado
                if (this.expression !== 'idle' && !isDragging) {
                    this.expressionTimer -= dt;
                    if (this.expressionTimer <= 0) {
                        this.expression = 'idle';
                    }
                }

                if (!isDragging && !this.isTyping && this.expression === 'idle') {
                    this.idleTime += dt;
                    if (this.idleTime > 7.5) {
                        this.triggerReaction('yawn', 3.6);
                        this.idleTime = 0;
                    }
                }

                // 2. Piscar Natural dos Olhos
                this.blinkTimer -= dt;
                if (this.blinkTimer <= 0) {
                    this.isBlinking = true;
                    setTimeout(() => { this.isBlinking = false; }, 135);
                    this.blinkTimer = 2.6 + Math.random() * 2.4;
                }

                // 3. Movimento dos Olhos (Segue o mouse, escaneia texto ao digitar ou olha ao redor)
                let lookTargetX = globalMouse.x * 0.11;
                let lookTargetY = globalMouse.y * 0.08;
                if (this.isTyping && this.isChatOpen) {
                    lookTargetX = 0.08 + Math.sin(time * 9) * 0.05;
                    lookTargetY = -0.02;
                } else if (this.idleTime > 2.5) {
                    lookTargetX = Math.sin(time * 1.4) * 0.08;
                    lookTargetY = Math.cos(time * 1.1) * 0.04;
                }
                this.eyeLook.x = THREE.MathUtils.lerp(this.eyeLook.x, lookTargetX, 0.14);
                this.eyeLook.y = THREE.MathUtils.lerp(this.eyeLook.y, lookTargetY, 0.14);

                // Posiciona os olhos exatamente na superfície curva frontal do Slime
                [-1, 1].forEach(side => {
                    const holder = side === -1 ? this.leftEyeHolder : this.rightEyeHolder;
                    const mesh = side === -1 ? this.leftEyeMesh : this.rightEyeMesh;

                    const baseLon = side * 0.455 + this.eyeLook.x; // ~26 graus como na folha de modelo
                    const baseLat = -0.055 + this.eyeLook.y;

                    const nx = Math.sin(baseLon) * Math.cos(baseLat);
                    const ny = Math.sin(baseLat);
                    const nz = Math.cos(baseLon) * Math.cos(baseLat);

                    const surfPt = evalSlimeSurface(nx, ny, nz);
                    holder.position.copy(surfPt).multiplyScalar(0.992);

                    const normalOut = new THREE.Vector3(nx, ny * 0.8, nz).normalize();
                    holder.lookAt(holder.position.clone().add(normalOut));

                    // Escala vertical do olho conforme piscada / bocejo / surpresa
                    let scaleY = this.baseEyeScale.y;
                    let scaleX = this.baseEyeScale.x;
                    if (this.isBlinking) {
                        scaleY *= 0.12;
                        scaleX *= 1.15;
                    } else if (this.expression === 'yawn') {
                        scaleY *= 0.32;
                        scaleX *= 1.12;
                    } else if (this.expression === 'dizzy' || isDragging) {
                        scaleY *= 1.22;
                        scaleX *= 1.18;
                    }
                    mesh.scale.set(
                        THREE.MathUtils.lerp(mesh.scale.x, scaleX, 0.25),
                        THREE.MathUtils.lerp(mesh.scale.y, scaleY, 0.25),
                        this.baseEyeScale.z
                    );
                });

                // Alterna entre olhos normais, olhos em arco (^ ^) e boquinha curva vs aberta
                const showHappyArcs = (this.expression === 'happy' || this.expression === 'love');
                this.leftEyeHolder.visible = !showHappyArcs;
                this.rightEyeHolder.visible = !showHappyArcs;
                this.happyEyesGroup.visible = showHappyArcs;

                const targetBlush = (showHappyArcs || isDragging) ? 0.32 : 0.0;
                this.blushMat.opacity = THREE.MathUtils.lerp(this.blushMat.opacity, targetBlush, 0.12);

                const showOpenMouth = (this.expression === 'yawn' || this.expression === 'dizzy' || isDragging);
                this.smileGroup.visible = !showOpenMouth;
                this.openMouthGroup.visible = showOpenMouth;

                if (showOpenMouth) {
                    const mouthScale = this.expression === 'yawn'
                        ? 1.05 + Math.sin(time * 4) * 0.15
                        : 0.72 + Math.sin(time * 14) * 0.1;
                    this.openMouthGroup.scale.setScalar(mouthScale);
                }

                // 4. Pulo de Alegria + Física de Mola (Squash & Stretch)
                let jumpY = 0;
                if (this.isJumping) {
                    this.jumpPhase += dt * 7.8;
                    if (this.jumpPhase < Math.PI) {
                        jumpY = Math.sin(this.jumpPhase) * 0.42;
                    } else {
                        this.isJumping = false;
                        this.triggerSquash(1.18, 0.82, 1.18, 0.9); // Impacto macio ao pousar
                    }
                }

                // Respiração orgânica de gelatina
                const breatheY = 1.0 + Math.sin(time * 2.6) * 0.022 + (this.expression === 'yawn' ? 0.11 : 0);
                const breatheXZ = 1.0 / Math.sqrt(breatheY);

                const stiffness = 140;
                const damping = 10.5;
                const ax = (breatheXZ - this.scaleSpring.x) * stiffness - this.scaleVel.x * damping;
                const ay = (breatheY - this.scaleSpring.y) * stiffness - this.scaleVel.y * damping;
                const az = (breatheXZ - this.scaleSpring.z) * stiffness - this.scaleVel.z * damping;

                this.scaleVel.x += ax * dt;
                this.scaleVel.y += ay * dt;
                this.scaleVel.z += az * dt;

                this.scaleSpring.x += this.scaleVel.x * dt;
                this.scaleSpring.y += this.scaleVel.y * dt;
                this.scaleSpring.z += this.scaleVel.z * dt;

                // Deformação de ondas de gelatina nos vértices quando sacudido / clicado
                this.jiggleIntensity = Math.max(0, this.jiggleIntensity - dt * 1.4);
                if (this.jiggleIntensity > 0.001 || isDragging) {
                    const pos = this.bodyGeo.attributes.position;
                    for (let i = 0; i < pos.count; i++) {
                        const bx = this.basePositions[i * 3];
                        const by = this.basePositions[i * 3 + 1];
                        const bz = this.basePositions[i * 3 + 2];

                        // Quando arrastado, o topo do Slime inclina elasticamente na direção do arraste
                        const heightFactor = THREE.MathUtils.clamp((by + 0.82) / 1.75, 0, 1);
                        const wave = Math.sin(by * 5.5 - time * 24) * 0.045 * this.jiggleIntensity * heightFactor;
                        const pullX = this.dragOffset.x * heightFactor * 0.35;
                        const pullY = this.dragOffset.y * heightFactor * 0.25;

                        pos.setXYZ(
                            i,
                            bx * (1 + wave) + pullX,
                            by + pullY,
                            bz * (1 - wave)
                        );
                    }
                    pos.needsUpdate = true;
                }

                if (!isDragging) {
                    this.dragOffset.lerp(new THREE.Vector2(0, 0), 0.18);
                }

                // Aplica escala mantendo os pés na linha da base (-0.82)
                this.slimeGroup.scale.copy(this.scaleSpring);
                const baseCompensation = (this.scaleSpring.y - 1.0) * 0.82;
                this.slimeGroup.position.y = baseCompensation + jumpY;

                // Ajusta a sombra de contato conforme a altura do pulo e largura do squash
                const shadowScale = (1.0 - jumpY * 0.45) * this.scaleSpring.x;
                this.shadowMesh.scale.setScalar(Math.max(0.5, shadowScale));

                // 5. Rotação 360° (Turnaround + Inclinação suave para o cursor)
                if (!isDragging) {
                    const mouseYaw = globalMouse.x * 0.26;
                    const desiredY = this.targetRotY + mouseYaw;
                    this.currentRotY = THREE.MathUtils.lerp(this.currentRotY, desiredY, 0.1);
                    this.currentRotX = THREE.MathUtils.lerp(this.currentRotX, -globalMouse.y * 0.12, 0.1);
                }
                this.slimeGroup.rotation.y = this.currentRotY;
                this.slimeGroup.rotation.x = this.currentRotX;

                // 6. Partículas Flutuantes (Quando bocejando, feliz ou Aqua Slime)
                const showBubbles = (this.expression === 'yawn' || this.expression === 'love' || this.modelConfig.accessory === 'bubbles');
                this.particles.forEach((p, idx) => {
                    p.mesh.visible = showBubbles;
                    if (showBubbles) {
                        const t = (time * p.speed + p.phase) % 2.4;
                        const normT = t / 2.4;
                        const angle = idx * 1.05 + time * 0.8;
                        p.mesh.position.set(
                            Math.cos(angle) * p.radius * 0.65,
                            -0.2 + normT * 1.55,
                            Math.sin(angle) * p.radius * 0.65
                        );
                        p.mesh.scale.setScalar(Math.sin(normT * Math.PI) * 1.1);
                    }
                });
            }
        }
export function createOriginalPinkSlime(scene) {
  return new PinkSlimeAvatar(scene)
}
