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
  const { currentScreen, transition } = useProject();
  const currentIdx = SCREEN_TO_STEP[currentScreen] ?? 0;

  const handleReset = () => {
    if (!window.confirm('처음부터 다시 시작할까요? 현재 작업이 모두 지워집니다.')) return;
    transition('RESET');
  };

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
      <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {currentScreen !== 's1' && (
          <button
            onClick={handleReset}
            style={{ fontSize: 12, padding: '2px 10px', opacity: 0.7 }}
          >
            처음으로
          </button>
        )}
        {rightContent}
      </span>
    </div>
  );
}
