import React from 'react';
import {Audio} from '@remotion/media';
import {loadFont} from '@remotion/fonts';
import {
	AbsoluteFill,
	Easing,
	Sequence,
	interpolate,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';

for (const [file, weight] of [
	['Poppins-SemiBold.ttf', '600'],
	['Poppins-Bold.ttf', '700'],
	['Poppins-ExtraBold.ttf', '800'],
]) {
	loadFont({family: 'Poppins', url: staticFile(`fonts/${file}`), weight});
}

export type Palette = {bg1: string; bg2: string; accent: string};
export type Question = {question: string; options: string[]; answerIndex: number; funFact: string};
// All frame numbers below come from Python (trivia/timeline.py). Remotion never guesses timings.
export type QuestionTiming = {
	from: number; // absolute start frame of the question scene
	dur: number; // scene length in frames
	optionsAt: number[]; // relative to scene start: when each option's narration begins
	timerAt: number; // relative: countdown start
	revealAt: number; // relative: timerAt + timerFrames
};
export type ReelProps = {
	topic: string;
	handle: string;
	palette: Palette;
	questions: Question[];
	audio: string | null; // path inside public/, e.g. "run/master.wav"
	timeline: {
		fps: number;
		totalFrames: number;
		timerFrames: number;
		hook: {from: number; dur: number};
		outro: {from: number; dur: number};
		questions: QuestionTiming[];
	};
};

const GOLD = '#F5C542';
const GREEN = '#22C55E';
const WHITE = '#FFFFFF';
const INK = '#1A0638';
// Instagram safe zone: nothing important above y=250 or below y=1580 (1920-340).
const SIDE = 110;
const WIDTH = 1080 - SIDE * 2;
const font: React.CSSProperties = {fontFamily: 'Poppins', color: WHITE};

const pop = (frame: number, fps: number, delay = 0) =>
	spring({frame: frame - delay, fps, config: {damping: 14, stiffness: 140, mass: 0.7}});

const sizeFor = (text: string, steps: [number, number][], min: number) => {
	for (const [maxLen, size] of steps) if (text.length <= maxLen) return size;
	return min;
};

const Background: React.FC<{palette: Palette}> = ({palette}) => {
	const frame = useCurrentFrame();
	const t = frame / 30;
	return (
		<AbsoluteFill style={{background: `linear-gradient(170deg, ${palette.bg1} 0%, #2B0B57 45%, ${palette.bg2} 100%)`}}>
			<div
				style={{
					position: 'absolute',
					width: 900,
					height: 900,
					borderRadius: '50%',
					left: 540 - 450 + Math.sin(t * 0.35) * 160,
					top: 300 + Math.cos(t * 0.27) * 140,
					background: `radial-gradient(circle, ${palette.accent}33 0%, transparent 65%)`,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					width: 800,
					height: 800,
					borderRadius: '50%',
					left: 540 - 400 + Math.cos(t * 0.3) * 200,
					top: 1100 + Math.sin(t * 0.22) * 160,
					background: `radial-gradient(circle, ${GOLD}22 0%, transparent 65%)`,
				}}
			/>
		</AbsoluteFill>
	);
};

const QuestionMarkBadge: React.FC<{size: number}> = ({size}) => (
	<div
		style={{
			width: size,
			height: size,
			borderRadius: '50%',
			border: `${size * 0.07}px solid ${GOLD}`,
			background: 'radial-gradient(circle, #5B1E9C 0%, #2B0B57 100%)',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			boxShadow: `0 0 ${size * 0.35}px ${GOLD}55`,
		}}
	>
		<span style={{...font, fontWeight: 800, fontSize: size * 0.62, lineHeight: 1}}>?</span>
	</div>
);

const Hook: React.FC<{topic: string; count: number; palette: Palette}> = ({topic, count, palette}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	// Frame 0 is fully composed (no fade from black) so the auto thumbnail looks right.
	const s1 = frame === 0 ? 1 : pop(frame, fps);
	const s2 = pop(frame, fps, 6);
	return (
		<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingTop: 250, paddingBottom: 340}}>
			<div style={{transform: `scale(${0.6 + 0.4 * s1}) rotate(${(1 - s1) * -20}deg)`}}>
				<QuestionMarkBadge size={360} />
			</div>
			<div style={{...font, fontWeight: 800, fontSize: 84, textAlign: 'center', width: WIDTH, marginTop: 70, lineHeight: 1.15}}>
				Can you score {count}/{count}?
			</div>
			<div
				style={{
					...font,
					fontWeight: 800,
					fontSize: sizeFor(topic, [[8, 120], [12, 100]], 84),
					color: GOLD,
					marginTop: 40,
					textTransform: 'uppercase',
					letterSpacing: 4,
					opacity: frame === 0 ? 1 : s2,
					transform: `translateY(${(1 - s2) * 40}px)`,
					textShadow: `0 0 40px ${palette.accent}88`,
				}}
			>
				{topic}
			</div>
		</AbsoluteFill>
	);
};

const Header: React.FC<{topic: string; index: number; total: number; palette: Palette}> = ({topic, index, total, palette}) => (
	<div style={{position: 'absolute', top: 262, left: SIDE, width: WIDTH}}>
		<div style={{display: 'flex', justifyContent: 'center'}}>
			<div
				style={{
					...font,
					fontWeight: 700,
					fontSize: 34,
					padding: '8px 30px',
					borderRadius: 40,
					border: `3px solid ${palette.accent}`,
					background: '#00000033',
					letterSpacing: 2,
				}}
			>
				{topic.toUpperCase()} · Q{index + 1}/{total}
			</div>
		</div>
		<div style={{marginTop: 22, height: 10, borderRadius: 5, background: '#FFFFFF22', overflow: 'hidden'}}>
			<div style={{width: `${((index + 1) / total) * 100}%`, height: '100%', background: GOLD, borderRadius: 5}} />
		</div>
	</div>
);

const Countdown: React.FC<{frame: number; total: number; fps: number}> = ({frame, total, fps}) => {
	const r = 78;
	const c = 2 * Math.PI * r;
	const progress = Math.min(Math.max(frame / total, 0), 1);
	const remaining = Math.max(Math.ceil((total - frame) / fps), 0);
	const inSecond = (frame % fps) / fps;
	const pulse = 1 + 0.08 * Math.max(0, 1 - inSecond * 4);
	return (
		<div style={{position: 'relative', width: 200, height: 200, transform: `scale(${pulse})`}}>
			<svg width={200} height={200} viewBox="0 0 200 200">
				<circle cx={100} cy={100} r={r} stroke="#FFFFFF26" strokeWidth={16} fill="#00000040" />
				<circle
					cx={100}
					cy={100}
					r={r}
					stroke={GOLD}
					strokeWidth={16}
					fill="none"
					strokeLinecap="round"
					strokeDasharray={c}
					strokeDashoffset={c * progress}
					transform="rotate(-90 100 100)"
				/>
			</svg>
			<div
				style={{
					...font,
					position: 'absolute',
					inset: 0,
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					fontWeight: 800,
					fontSize: 92,
				}}
			>
				{remaining}
			</div>
		</div>
	);
};

const QuestionScene: React.FC<{
	q: Question;
	timing: QuestionTiming;
	index: number;
	total: number;
	topic: string;
	palette: Palette;
	timerFrames: number;
}> = ({q, timing, index, total, topic, palette, timerFrames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const revealed = frame >= timing.revealAt;
	const qIn = pop(frame, fps);
	const qSize = sizeFor(q.question, [[45, 72], [70, 64], [90, 58]], 52);
	const revealPop = pop(frame, fps, timing.revealAt);
	const out = interpolate(frame, [timing.revealAt + 0, timing.revealAt + 8], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const timerIn = interpolate(frame, [timing.timerAt - 6, timing.timerAt], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	return (
		<AbsoluteFill>
			<Header topic={topic} index={index} total={total} palette={palette} />
			<div
				style={{
					position: 'absolute',
					top: 390,
					left: SIDE,
					width: WIDTH,
					height: 340,
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
				}}
			>
				<div
					style={{
						...font,
						fontWeight: 800,
						fontSize: qSize,
						lineHeight: 1.15,
						textAlign: 'center',
						opacity: qIn,
						transform: `translateY(${(1 - qIn) * 40}px) scale(${0.94 + 0.06 * qIn})`,
						textShadow: '0 4px 18px #00000066',
					}}
				>
					{q.question}
				</div>
			</div>
			<div style={{position: 'absolute', top: 750, left: SIDE, width: WIDTH, display: 'flex', flexDirection: 'column', gap: 20}}>
				{q.options.map((opt, i) => {
					const appear = pop(frame, fps, timing.optionsAt[i] - 3);
					const correct = i === q.answerIndex;
					const bg = revealed && correct ? GREEN : '#FFFFFF14';
					const border = revealed && correct ? '#86EFAC' : '#FFFFFF2E';
					const opacity = appear * (revealed && !correct ? 1 - 0.62 * out : 1);
					const scale = revealed && correct ? 1 + 0.05 * Math.sin(Math.min(revealPop, 1) * Math.PI) : 1;
					return (
						<div
							key={i}
							style={{
								height: 120,
								borderRadius: 28,
								background: bg,
								border: `3px solid ${border}`,
								display: 'flex',
								alignItems: 'center',
								padding: '0 26px',
								gap: 24,
								opacity,
								transform: `translateX(${(1 - appear) * 80}px) scale(${scale})`,
								boxShadow: revealed && correct ? `0 0 40px ${GREEN}88` : 'none',
							}}
						>
							<div
								style={{
									...font,
									flex: '0 0 76px',
									height: 76,
									borderRadius: '50%',
									background: revealed && correct ? WHITE : GOLD,
									color: revealed && correct ? GREEN : INK,
									fontWeight: 800,
									fontSize: 42,
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
								}}
							>
								{'ABCD'[i]}
							</div>
							<div
								style={{
									...font,
									fontWeight: 700,
									fontSize: sizeFor(opt, [[14, 52], [20, 46], [26, 40]], 36),
									lineHeight: 1.1,
								}}
							>
								{opt}
							</div>
						</div>
					);
				})}
			</div>
			<div style={{position: 'absolute', top: 1320, left: SIDE, width: WIDTH, height: 255, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
				{!revealed && frame >= timing.timerAt - 6 ? (
					<div style={{opacity: timerIn}}>
						<Countdown frame={frame - timing.timerAt} total={timerFrames} fps={fps} />
					</div>
				) : null}
				{revealed ? (
					<div
						style={{
							width: WIDTH,
							borderRadius: 28,
							border: `3px solid ${GOLD}`,
							background: '#00000055',
							padding: '18px 28px',
							opacity: out,
							transform: `translateY(${(1 - revealPop) * 40}px)`,
						}}
					>
						<div style={{...font, fontWeight: 800, fontSize: 30, color: GOLD, letterSpacing: 3}}>DID YOU KNOW?</div>
						<div style={{...font, fontWeight: 600, fontSize: sizeFor(q.funFact, [[70, 42]], 38), lineHeight: 1.2, marginTop: 6}}>
							{q.funFact}
						</div>
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

const Outro: React.FC<{handle: string}> = ({handle}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = pop(frame, fps);
	const s2 = pop(frame, fps, 8);
	return (
		<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingTop: 250, paddingBottom: 340}}>
			<div style={{transform: `scale(${s})`}}>
				<QuestionMarkBadge size={260} />
			</div>
			<div style={{...font, fontWeight: 800, fontSize: 88, marginTop: 70, textAlign: 'center', width: WIDTH, lineHeight: 1.1, opacity: s}}>
				Comment your score!
			</div>
			<div style={{...font, fontWeight: 700, fontSize: 52, marginTop: 40, color: GOLD, opacity: s2, transform: `translateY(${(1 - s2) * 30}px)`}}>
				Follow @{handle}
			</div>
			<div style={{...font, fontWeight: 600, fontSize: 46, marginTop: 10, opacity: s2}}>for daily trivia</div>
		</AbsoluteFill>
	);
};

export const QuizReel: React.FC<ReelProps> = ({topic, handle, palette, questions, audio, timeline}) => {
	const frame = useCurrentFrame();
	const sceneFade = (from: number, dur: number) =>
		interpolate(frame, [from, from + 6, from + dur - 6, from + dur], [0, 1, 1, 0], {
			extrapolateLeft: 'clamp',
			extrapolateRight: 'clamp',
			easing: Easing.inOut(Easing.ease),
		});
	return (
		<AbsoluteFill>
			<Background palette={palette} />
			{audio ? <Audio src={staticFile(audio)} /> : null}
			<Sequence from={timeline.hook.from} durationInFrames={timeline.hook.dur}>
				<AbsoluteFill style={{opacity: frame === 0 ? 1 : sceneFade(timeline.hook.from - 6, timeline.hook.dur + 6)}}>
					<Hook topic={topic} count={questions.length} palette={palette} />
				</AbsoluteFill>
			</Sequence>
			{questions.map((q, i) => {
				const t = timeline.questions[i];
				return (
					<Sequence key={i} from={t.from} durationInFrames={t.dur}>
						<AbsoluteFill style={{opacity: sceneFade(t.from, t.dur)}}>
							<QuestionScene q={q} timing={t} index={i} total={questions.length} topic={topic} palette={palette} timerFrames={timeline.timerFrames} />
						</AbsoluteFill>
					</Sequence>
				);
			})}
			<Sequence from={timeline.outro.from} durationInFrames={timeline.outro.dur}>
				<AbsoluteFill style={{opacity: sceneFade(timeline.outro.from, timeline.outro.dur + 6)}}>
					<Outro handle={handle} />
				</AbsoluteFill>
			</Sequence>
		</AbsoluteFill>
	);
};
