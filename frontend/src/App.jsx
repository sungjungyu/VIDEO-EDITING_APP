import { useProject } from './state/ProjectContext.jsx';
import ClipImport    from './components/s1/ClipImport.jsx';
import RequestScreen from './components/s2/RequestScreen.jsx';
import AnalyzingScreen  from './components/s3/AnalyzingScreen.jsx';
import StructureEditor  from './components/s4/StructureEditor.jsx';
import RenderingScreen  from './components/s5/RenderingScreen.jsx';
import ResultView       from './components/s5_1/ResultView.jsx';
import ErrorBoundary    from './components/common/ErrorBoundary.jsx';
import NotConnected     from './components/common/NotConnected.jsx';
import { USE_MOCK }     from './api/index.js';

const SCREENS = {
  s1:  ClipImport,
  s2:  RequestScreen,
  s3:  AnalyzingScreen,
  s4:  StructureEditor,
  s5:  RenderingScreen,
  s51: ResultView,
};

export default function App() {
  const { currentScreen } = useProject();
  // 실제 모드: 렌더(S5)·결과(S5-1)는 아직 서버와 연결 전이라 예시 데이터 대신 안내 화면
  const Screen = !USE_MOCK && (currentScreen === 's5' || currentScreen === 's51') ? NotConnected : SCREENS[currentScreen];
  return (
    <ErrorBoundary key={currentScreen}>
      <div style={{ padding: '0 16px' }}>
        {Screen ? <Screen /> : <div>알 수 없는 화면: {currentScreen}</div>}
      </div>
    </ErrorBoundary>
  );
}
