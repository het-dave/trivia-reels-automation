import React from 'react';
import {Composition} from 'remotion';
import {QuizReel, type ReelProps} from './QuizReel';
import sample from './sample.json';

export const RemotionRoot: React.FC = () => (
	<Composition
		id="QuizReel"
		component={QuizReel}
		width={1080}
		height={1920}
		fps={30}
		durationInFrames={300}
		defaultProps={sample as ReelProps}
		calculateMetadata={({props}) => ({durationInFrames: props.timeline.totalFrames, fps: props.timeline.fps})}
	/>
);
