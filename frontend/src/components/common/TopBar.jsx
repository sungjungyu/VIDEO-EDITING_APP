import { useProject } from '../../state/ProjectContext.jsx';

const STEPS = [
  { key: 's1',  label: '① 가져오기' },
  { key: 's2',  label: '② 요청' },
  { key: 's3',  label: '③ 분석' },
  { key: 's4',  label: '④ 구조 편집' },
  { key: 's5',  label: '⑤ 결과' },
];

const SCREEN_TO_STEP = { s1: 0, s2: 1, s3: 2, s4: 3, s5: 4, s51: 4 };

export default function TopBar({ rightContent }) {
  const { currentScreen } = useProject();
  const currentIdx = SCREEN_TO_STEP[currentScreen] ?? 0;

  return (
    <div className="top-bar">
      <span>
        <span className="logo">V</span>
        {STEPS.map((step, i) => {
          const done    = i < currentIdx;
          const current = i === currentIdx;
          return (
            <span key={step.key}>
              {i > 0 && ' ─ '}
              {current
                ? <b>{step.label}</b>
                : done
                  ? <span>{step.label} ✔</span>
                  : <span>{step.label}</span>
              }
            </span>
          );
        })}
      </span>
      <span>{rightContent}</span>
    </div>
  );
}
