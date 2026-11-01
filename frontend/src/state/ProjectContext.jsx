import { createContext, useContext, useState } from 'react';

const ProjectContext = createContext(null);

export function ProjectProvider({ children }) {
  const [currentScreen, setCurrentScreen] = useState('s1');
  const [clips, setClips]                       = useState([]);
  const [judgmentRules, setJudgmentRules]       = useState(null);
  const [executionRules, setExecutionRules]     = useState(null);
  const [selection, setSelection]               = useState(null);

  return (
    <ProjectContext.Provider value={{
      currentScreen, setCurrentScreen,
      clips, setClips,
      judgmentRules, setJudgmentRules,
      executionRules, setExecutionRules,
      selection, setSelection,
    }}>
      {children}
    </ProjectContext.Provider>
  );
}

export const useProject = () => useContext(ProjectContext);
