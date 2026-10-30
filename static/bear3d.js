/**
 * 3D Gemmy animated dancing bear stage for the Bear control center.
 *
 * The model reacts to:
 *  - L298 #1 channel 1 mouth pulses
 *  - L298 #1 channel 2 body shimmy polarity (left / right)
 *  - L298 #2 tushie motor (out while powered, spring return when released)
 *  - 2-DOF spotlight pan / tilt / MOSFET brightness
 *  - stage turntable servo angle
 */

class Bear3DRenderer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0d0905);
        this.scene.fog = new THREE.FogExp2(0x0d0905, 0.0011);

        this.camera = new THREE.PerspectiveCamera(
            42,
            this.container.clientWidth / (this.container.clientHeight || 1),
            1,
            5000
        );
        this.camera.position.set(0, 190, 610);

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(this.container.clientWidth, this.container.clientHeight || 360);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.container.appendChild(this.renderer.domElement);

        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.06;
        this.controls.maxPolarAngle = Math.PI / 2 + 0.05;
        this.controls.minDistance = 220;
        this.controls.maxDistance = 1100;
        this.controls.target.set(0, 145, 0);

        this.mouthEnergized = false;
        this.bodyDirection = 'off';
        this.tushieOut = false;
        this.stageAngle = 90;
        this.spotlightPan = 90;
        this.spotlightTilt = 90;
        this.spotlightIntensity = 0;
        this.currentStageRotation = 0;
        this.currentPan = 0;
        this.currentTilt = 0;
        this.currentIntensity = 0;
        this.shimmyPhase = 0;
        this.shimmyAmount = 0;
        this.tushieAmount = 0;
        this.armPhase = 0;
        this.blinkPhase = 0;

        this.setupEnvironment();
        this.buildStage();

        window.addEventListener('resize', () => this.onWindowResize());
    }

    setupEnvironment() {
        this.scene.add(new THREE.AmbientLight(0xffedd5, 0.62));

        const hemi = new THREE.HemisphereLight(0xfde68a, 0x1c1917, 0.65);
        this.scene.add(hemi);

        const key = new THREE.DirectionalLight(0xfff1d6, 1.15);
        key.position.set(200, 340, 260);
        key.castShadow = true;
        key.shadow.mapSize.width = 2048;
        key.shadow.mapSize.height = 2048;
        this.scene.add(key);

        const rim = new THREE.PointLight(0xf59e0b, 1.5, 1000);
        rim.position.set(-280, 190, -180);
        this.scene.add(rim);

        const fill = new THREE.PointLight(0xfbbf24, 0.7, 800);
        fill.position.set(220, 80, 220);
        this.scene.add(fill);
    }

    buildStage() {
        this.mats = {
            stage: new THREE.MeshStandardMaterial({ color: 0x2b1d12, roughness: 0.6, metalness: 0.4 }),
            stageTop: new THREE.MeshStandardMaterial({ color: 0x92400e, roughness: 0.45, metalness: 0.3 }),
            brass: new THREE.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.25, metalness: 0.8 }),
            wood: new THREE.MeshStandardMaterial({ color: 0x5b3a1e, roughness: 0.85 }),
            woodDark: new THREE.MeshStandardMaterial({ color: 0x3f2412, roughness: 0.9 }),
            fur: new THREE.MeshStandardMaterial({ color: 0x8b5a2b, roughness: 0.92 }),
            furDark: new THREE.MeshStandardMaterial({ color: 0x5c3a1e, roughness: 0.95 }),
            furLight: new THREE.MeshStandardMaterial({ color: 0xc98a4b, roughness: 0.9 }),
            muzzle: new THREE.MeshStandardMaterial({ color: 0xe7c9a9, roughness: 0.8 }),
            innerEar: new THREE.MeshStandardMaterial({ color: 0xd99b7c, roughness: 0.85 }),
            nose: new THREE.MeshStandardMaterial({ color: 0x17110d, roughness: 0.35 }),
            mouth: new THREE.MeshStandardMaterial({ color: 0x3b1210, roughness: 0.7 }),
            tongue: new THREE.MeshStandardMaterial({ color: 0xc2415c, roughness: 0.7 }),
            eyeWhite: new THREE.MeshStandardMaterial({ color: 0xfefce8, roughness: 0.3 }),
            pupil: new THREE.MeshStandardMaterial({ color: 0x0b0b0b, roughness: 0.1 }),
            highlight: new THREE.MeshBasicMaterial({ color: 0xffffff }),
            claw: new THREE.MeshStandardMaterial({ color: 0x2a211b, roughness: 0.6 }),
            metal: new THREE.MeshStandardMaterial({ color: 0x334155, metalness: 0.9, roughness: 0.2 }),
            bulb: new THREE.MeshStandardMaterial({
                color: 0xfff3c4,
                emissive: 0xfff3c4,
                emissiveIntensity: 0.1,
                roughness: 0.15
            })
        };

        this.stageGroup = new THREE.Group();
        this.scene.add(this.stageGroup);

        const base = new THREE.Mesh(new THREE.CylinderGeometry(165, 180, 18, 48), this.mats.stage);
        base.position.y = 9;
        base.receiveShadow = true;
        base.castShadow = true;
        this.stageGroup.add(base);

        const top = new THREE.Mesh(new THREE.CylinderGeometry(158, 158, 4, 48), this.mats.stageTop);
        top.position.y = 20;
        top.receiveShadow = true;
        this.stageGroup.add(top);

        const ring = new THREE.Mesh(new THREE.TorusGeometry(148, 2.6, 12, 64), this.mats.brass);
        ring.rotation.x = Math.PI / 2;
        ring.position.y = 23;
        this.stageGroup.add(ring);

        const floor = new THREE.Mesh(
            new THREE.CircleGeometry(460, 64),
            new THREE.MeshStandardMaterial({ color: 0x1a1008, roughness: 0.96, metalness: 0.04 })
        );
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = -1;
        floor.receiveShadow = true;
        this.scene.add(floor);

        const grid = new THREE.GridHelper(920, 32, 0xf59e0b, 0x4a2d12);
        grid.position.y = 0;
        this.scene.add(grid);

        this.buildPedestal();
        this.buildBear();
        this.buildSpotlight();
    }

    buildPedestal() {
        const riser = new THREE.Mesh(new THREE.CylinderGeometry(88, 96, 10, 40), this.mats.wood);
        riser.position.y = 27;
        riser.castShadow = true;
        riser.receiveShadow = true;
        this.stageGroup.add(riser);

        const rim = new THREE.Mesh(new THREE.TorusGeometry(90, 3, 12, 48), this.mats.brass);
        rim.rotation.x = Math.PI / 2;
        rim.position.y = 33;
        this.stageGroup.add(rim);
    }

    buildBear() {
        this.bearGroup = new THREE.Group();
        this.bearGroup.position.set(0, 108, 0);
        this.stageGroup.add(this.bearGroup);

        this.bodyGroup = new THREE.Group();
        this.bodyGroup.position.set(0, 34, -2);
        this.bearGroup.add(this.bodyGroup);

        const torso = new THREE.Mesh(new THREE.SphereGeometry(50, 32, 26), this.mats.fur);
        torso.scale.set(1.0, 1.28, 0.88);
        torso.castShadow = true;
        this.bodyGroup.add(torso);

        const belly = new THREE.Mesh(new THREE.SphereGeometry(33, 24, 18), this.mats.furLight);
        belly.scale.set(0.95, 1.12, 0.52);
        belly.position.set(0, -4, 33);
        this.bodyGroup.add(belly);

        const chestTuft = new THREE.Mesh(new THREE.SphereGeometry(20, 18, 14), this.mats.muzzle);
        chestTuft.scale.set(1.0, 0.75, 0.45);
        chestTuft.position.set(0, 22, 36);
        this.bodyGroup.add(chestTuft);

        // Legs and feet
        for (const side of [-1, 1]) {
            const leg = new THREE.Mesh(new THREE.CylinderGeometry(15, 18, 42, 14), this.mats.furDark);
            leg.position.set(side * 22, -40, 8);
            leg.rotation.z = side * 0.06;
            leg.castShadow = true;
            this.bodyGroup.add(leg);

            const foot = new THREE.Mesh(new THREE.SphereGeometry(21, 20, 14), this.mats.furDark);
            foot.scale.set(1.05, 0.52, 1.5);
            foot.position.set(side * 24, -60, 22);
            foot.castShadow = true;
            this.bodyGroup.add(foot);

            for (let i = 0; i < 3; i++) {
                const claw = new THREE.Mesh(new THREE.ConeGeometry(3.2, 9, 8), this.mats.claw);
                claw.position.set(side * 24 + (i - 1) * 8, -62, 44);
                claw.rotation.x = Math.PI / 2;
                this.bodyGroup.add(claw);
            }
        }

        // Arms
        this.armGroups = [];
        for (const side of [-1, 1]) {
            const arm = new THREE.Group();
            arm.position.set(side * 46, 42, 2);
            arm.userData.side = side;
            this.bodyGroup.add(arm);

            const upper = new THREE.Mesh(new THREE.CylinderGeometry(13, 11, 46, 12), this.mats.fur);
            upper.position.set(side * 9, -20, 0);
            upper.rotation.z = side * 0.28;
            upper.castShadow = true;
            arm.add(upper);

            const paw = new THREE.Mesh(new THREE.SphereGeometry(15, 16, 12), this.mats.furDark);
            paw.scale.set(0.9, 0.85, 1.0);
            paw.position.set(side * 15, -43, 3);
            paw.castShadow = true;
            arm.add(paw);

            arm.rotation.z = side * 0.08;
            this.armGroups.push(arm);
        }

        // Head
        this.headGroup = new THREE.Group();
        this.headGroup.position.set(0, 76, 10);
        this.bodyGroup.add(this.headGroup);

        const head = new THREE.Mesh(new THREE.SphereGeometry(37, 30, 24), this.mats.fur);
        head.scale.set(1.05, 0.98, 0.95);
        head.castShadow = true;
        this.headGroup.add(head);

        for (const side of [-1, 1]) {
            const ear = new THREE.Mesh(new THREE.SphereGeometry(16, 18, 14), this.mats.furDark);
            ear.position.set(side * 31, 22, -2);
            ear.castShadow = true;
            this.headGroup.add(ear);

            const inner = new THREE.Mesh(new THREE.SphereGeometry(9, 14, 12), this.mats.innerEar);
            inner.scale.set(0.8, 0.9, 0.45);
            inner.position.set(side * 31, 22, 12);
            this.headGroup.add(inner);
        }

        // Muzzle and nose
        const muzzle = new THREE.Mesh(new THREE.SphereGeometry(23, 24, 18), this.mats.muzzle);
        muzzle.scale.set(1.2, 0.82, 0.9);
        muzzle.position.set(0, -9, 29);
        this.headGroup.add(muzzle);

        const nose = new THREE.Mesh(new THREE.SphereGeometry(9, 16, 12), this.mats.nose);
        nose.scale.set(1.15, 0.7, 0.7);
        nose.position.set(0, -3, 48);
        this.headGroup.add(nose);

        // Eyes
        this.eyeGroups = [];
        for (const side of [-1, 1]) {
            const eyeGroup = new THREE.Group();
            eyeGroup.position.set(side * 14, 9, 30);

            const white = new THREE.Mesh(new THREE.SphereGeometry(6.2, 16, 16), this.mats.eyeWhite);
            eyeGroup.add(white);

            const pupil = new THREE.Mesh(new THREE.SphereGeometry(3.5, 14, 14), this.mats.pupil);
            pupil.position.z = 3.9;
            eyeGroup.add(pupil);

            const glint = new THREE.Mesh(new THREE.SphereGeometry(1.0, 8, 8), this.mats.highlight);
            glint.position.set(1.4, 1.4, 6.2);
            eyeGroup.add(glint);

            const brow = new THREE.Mesh(new THREE.BoxGeometry(11, 2.6, 3), this.mats.furDark);
            brow.position.set(0, 9, 1);
            brow.rotation.z = side * -0.12;
            eyeGroup.add(brow);

            this.headGroup.add(eyeGroup);
            this.eyeGroups.push(eyeGroup);
        }

        // Lower jaw, driven by the mouth motor
        this.lowerJawGroup = new THREE.Group();
        this.lowerJawGroup.position.set(0, -20, 24);
        this.headGroup.add(this.lowerJawGroup);

        const jaw = new THREE.Mesh(new THREE.SphereGeometry(16, 18, 12), this.mats.muzzle);
        jaw.scale.set(1.1, 0.5, 0.95);
        jaw.position.set(0, -1, 13);
        this.lowerJawGroup.add(jaw);

        const innerMouth = new THREE.Mesh(new THREE.SphereGeometry(11, 16, 12), this.mats.mouth);
        innerMouth.scale.set(0.95, 0.35, 0.7);
        innerMouth.position.set(0, 2, 13);
        this.lowerJawGroup.add(innerMouth);

        const tongue = new THREE.Mesh(new THREE.SphereGeometry(7, 12, 10), this.mats.tongue);
        tongue.scale.set(1.0, 0.28, 0.8);
        tongue.position.set(0, 3, 17);
        this.lowerJawGroup.add(tongue);

        // Tushie: pushed out by the second L298, pulled back by its spring
        this.tushieGroup = new THREE.Group();
        this.tushieBaseZ = -34;
        this.tushieGroup.position.set(0, 16, this.tushieBaseZ);
        this.bodyGroup.add(this.tushieGroup);

        const rump = new THREE.Mesh(new THREE.SphereGeometry(32, 26, 20), this.mats.furDark);
        rump.scale.set(1.0, 0.9, 0.8);
        rump.castShadow = true;
        this.tushieGroup.add(rump);

        for (const side of [-1, 1]) {
            const cheek = new THREE.Mesh(new THREE.SphereGeometry(17, 18, 14), this.mats.fur);
            cheek.scale.set(0.9, 0.85, 0.7);
            cheek.position.set(side * 20, -4, -8);
            this.tushieGroup.add(cheek);
        }

        const tail = new THREE.Mesh(new THREE.SphereGeometry(11, 14, 12), this.mats.furLight);
        tail.scale.set(0.9, 0.9, 0.7);
        tail.position.set(0, 16, -14);
        this.tushieGroup.add(tail);
    }

    buildSpotlight() {
        this.spotlightGroup = new THREE.Group();
        this.spotlightGroup.position.set(0, 0, 120);
        this.stageGroup.add(this.spotlightGroup);

        const base = new THREE.Mesh(new THREE.CylinderGeometry(16, 20, 8, 20), this.mats.metal);
        base.position.y = 4;
        this.spotlightGroup.add(base);

        const pole = new THREE.Mesh(new THREE.CylinderGeometry(4, 4, 140, 12), this.mats.metal);
        pole.position.y = 72;
        this.spotlightGroup.add(pole);

        this.panGroup = new THREE.Group();
        this.panGroup.position.set(0, 146, 0);
        this.spotlightGroup.add(this.panGroup);

        this.tiltGroup = new THREE.Group();
        this.panGroup.add(this.tiltGroup);

        const yoke = new THREE.Mesh(new THREE.BoxGeometry(28, 14, 14), this.mats.metal);
        this.tiltGroup.add(yoke);

        const housing = new THREE.Mesh(new THREE.CylinderGeometry(15, 12, 34, 20), this.mats.metal);
        housing.rotation.x = Math.PI / 2;
        housing.position.z = -18;
        this.tiltGroup.add(housing);

        this.lens = new THREE.Mesh(new THREE.CircleGeometry(12, 24), this.mats.bulb);
        this.lens.position.z = -35.2;
        this.lens.rotation.y = Math.PI;
        this.tiltGroup.add(this.lens);

        this.beam = new THREE.Mesh(
            new THREE.CylinderGeometry(34, 2, 300, 28, 1, true),
            new THREE.MeshBasicMaterial({
                color: 0xfff3c4,
                transparent: true,
                opacity: 0.0,
                side: THREE.DoubleSide,
                depthWrite: false,
                blending: THREE.AdditiveBlending
            })
        );
        this.beam.rotation.x = -Math.PI / 2;
        this.beam.position.z = -150;
        this.tiltGroup.add(this.beam);

        this.spotLight = new THREE.SpotLight(0xfff3c4, 0, 1000, Math.PI / 7, 0.45, 1.2);
        this.spotLight.position.set(0, 0, -34);
        this.tiltGroup.add(this.spotLight);

        this.spotTarget = new THREE.Object3D();
        this.spotTarget.position.set(0, 0, -380);
        this.tiltGroup.add(this.spotTarget);
        this.spotLight.target = this.spotTarget;
    }

    updatePose(bodyState, overrideState) {
        if (overrideState) {
            if ('mouth_channel1' in overrideState) {
                this.mouthEnergized = overrideState.mouth_channel1 === 'open';
            }
            if ('body_channel2' in overrideState) {
                const direction = overrideState.body_channel2;
                this.bodyDirection = (direction === 'left' || direction === 'right') ? direction : 'off';
            }
            if ('tushie' in overrideState) {
                this.tushieOut = !!overrideState.tushie;
            }
            if (overrideState.stage && overrideState.stage.angle !== undefined) {
                this.stageAngle = overrideState.stage.angle;
            }
            if (overrideState.spotlight) {
                this.spotlightPan = overrideState.spotlight.pan;
                this.spotlightTilt = overrideState.spotlight.tilt;
                this.spotlightIntensity = overrideState.spotlight.intensity;
            }
        }

        const now = performance.now();

        // Stage turntable
        const targetRotation = THREE.MathUtils.degToRad(this.stageAngle - 90);
        this.currentStageRotation += (targetRotation - this.currentStageRotation) * 0.08;
        this.stageGroup.rotation.y = this.currentStageRotation;

        // Spotlight aim
        const targetPan = THREE.MathUtils.degToRad(this.spotlightPan - 90);
        const targetTilt = THREE.MathUtils.degToRad(90 - this.spotlightTilt);
        this.currentPan += (targetPan - this.currentPan) * 0.24;
        this.currentTilt += (targetTilt - this.currentTilt) * 0.24;
        this.panGroup.rotation.y = this.currentPan;
        this.tiltGroup.rotation.x = this.currentTilt;

        // Spotlight brightness / breathing / flash
        const targetIntensity = Math.max(0, Math.min(100, this.spotlightIntensity)) / 100;
        this.currentIntensity += (targetIntensity - this.currentIntensity) * 0.45;
        const glow = this.currentIntensity;
        if (this.lens && this.lens.material) {
            this.lens.material.emissiveIntensity = 0.1 + glow * 4.0;
        }
        if (this.spotLight) {
            this.spotLight.intensity = glow * 3.4;
        }
        if (this.beam && this.beam.material) {
            this.beam.material.opacity = glow * 0.17;
        }

        // Mouth pulse
        if (this.lowerJawGroup) {
            if (this.mouthEnergized) {
                const pulse = 0.18 + Math.abs(Math.sin(now * 0.019)) * 0.5;
                this.lowerJawGroup.rotation.x = pulse;
            } else {
                this.lowerJawGroup.rotation.x += (0.04 - this.lowerJawGroup.rotation.x) * 0.25;
            }
        }

        // Body shimmy: direction sets the polarity / phase of the sway
        const shimmying = this.bodyDirection === 'left' || this.bodyDirection === 'right';
        const direction = this.bodyDirection === 'right' ? 1 : -1;
        this.shimmyPhase += shimmying ? 0.19 : 0.08;
        const targetShimmy = shimmying ? 1 : 0;
        this.shimmyAmount += (targetShimmy - this.shimmyAmount) * 0.16;
        const sway = Math.sin(this.shimmyPhase) * 9 * this.shimmyAmount * direction;
        const lean = Math.sin(this.shimmyPhase) * 0.075 * this.shimmyAmount * direction;

        if (this.bodyGroup) {
            this.bodyGroup.position.x = sway;
            this.bodyGroup.rotation.z = -lean;
            this.bodyGroup.rotation.y = Math.sin(this.shimmyPhase * 0.5) * 0.04 * this.shimmyAmount * direction;
        }
        if (this.headGroup) {
            this.headGroup.rotation.z = lean * 0.55;
            this.headGroup.rotation.x = Math.sin(now * 0.0012) * 0.025;
        }

        // Arms swing when dancing, relax when idle
        this.armPhase += shimmying ? 0.22 : 0.08;
        if (this.armGroups) {
            this.armGroups.forEach((arm) => {
                const side = arm.userData.side;
                const target = shimmying
                    ? side * 0.18 + Math.sin(this.armPhase + (side > 0 ? Math.PI : 0)) * 0.5
                    : side * 0.08;
                arm.rotation.x += (target - arm.rotation.x) * 0.2;
                arm.rotation.z = side * (0.08 + Math.abs(Math.sin(this.shimmyPhase)) * 0.12 * this.shimmyAmount);
            });
        }

        // Tushie motor drives the rump out; spring return when power is removed
        const targetTushie = this.tushieOut ? 1 : 0;
        this.tushieAmount += (targetTushie - this.tushieAmount) * 0.25;
        if (this.tushieGroup) {
            this.tushieGroup.position.z = this.tushieBaseZ - this.tushieAmount * 22;
            this.tushieGroup.rotation.x = this.tushieAmount * 0.16;
            const scale = 1 + this.tushieAmount * 0.06;
            this.tushieGroup.scale.set(scale, scale, scale);
        }

        // Gentle visual blink so the bear feels alive
        this.blinkPhase += 0.016;
        const blink = Math.max(0.12, Math.min(1, Math.abs(Math.sin(this.blinkPhase * 0.32)) * 8));
        if (this.eyeGroups) {
            this.eyeGroups.forEach((group) => { group.scale.y = blink; });
        }
    }

    render() {
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    onWindowResize() {
        const parent = (this.renderer && this.renderer.domElement && this.renderer.domElement.parentElement)
            ? this.renderer.domElement.parentElement : this.container;
        const targetContainer = parent || this.container;
        if (!targetContainer) return;

        const width = targetContainer.clientWidth || targetContainer.offsetWidth || 800;
        const height = targetContainer.clientHeight || targetContainer.offsetHeight || 360;

        if (width > 0 && height > 0) {
            this.container = targetContainer;
            this.camera.aspect = width / height;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(width, height);
        }
    }
}
