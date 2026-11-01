import { useProject } from './state/ProjectContext.jsx';
import ClipImport    from './components/s1/ClipImport.jsx';
import RequestScreen from './components/s2/RequestScreen.jsx';
import AnalyzingScreen  from './components/s3/AnalyzingScreen.jsx';
import StructureEditor  from './components/s4/StructureEditor.jsx';
import RenderingScreen  from './components/s5/RenderingScreen.jsx';
import ResultView       from './components/s5_1/ResultView.jsx';

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
  const Screen = SCREENS[currentScreen];
  return (
    <div style={{ padding: '0 16px' }}>
      {Screen ? <Screen /> : <div>알 수 없는 화면: {currentScreen}</div>}
    </div>
  );
}
