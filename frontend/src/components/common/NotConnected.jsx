import { useProject } from '../../state/ProjectContext.jsx';
import TopBar from './TopBar.jsx';
import BottomBar from './BottomBar.jsx';

export const RENDER_PLANNED = '렌더 연결은 11/22 예정이에요';

/** 실제 모드에서 아직 서버와 연결하지 않은 화면(S5 렌더, S5-1 결과). 예시(mock) 데이터를 보이지 않는다 */
export default function NotConnected() {
  const { status, transition, navigate } = useProject();
  const back = () => {
    if (status === 'rendering') transition('CANCEL_RENDER');
    else if (status === 'render_failed') transition('BACK_TO_EDITOR');
    else navigate('s4');
  };
  return (
    <div className="app-shell">
      <TopBar />
      <div className="progress-wrap" style={{ flex: 1 }}>
        <div className="progress-title">{RENDER_PLANNED}</div>
        <div className="lb" style={{ textAlign: 'center', lineHeight: 1.7 }}>
          지금은 구조 편집(④)까지 실제 서버와 연결되어 있어요.<br />
          렌더·결과 보기·내보내기는 서버 연결 작업 뒤에 열려요.
        </div>
      </div>
      <BottomBar left={<button onClick={back}>← 구조 편집으로</button>} right={null} />
    </div>
  );
}
