declare module 'react-cytoscapejs' {
  import type cytoscape from 'cytoscape';
  import type { ComponentType } from 'react';

  interface CytoscapeComponentProps {
    id?: string;
    cy?: (cy: cytoscape.Core) => void;
    style?: React.CSSProperties;
    stylesheet?: cytoscape.StylesheetCSS[];
    className?: string;
    elements?: cytoscape.ElementDefinition[];
    layout?: cytoscape.LayoutOptions;
    core?: cytoscape.Core;
    autoungrabify?: boolean;
    autounselectify?: boolean;
    boxSelectionEnabled?: boolean;
    wheelSensitivity?: number;
    minZoom?: number;
    maxZoom?: number;
    zoom?: number;
    pan?: { x: number; y: number };
    userZoomingEnabled?: boolean;
    userPanningEnabled?: boolean;
    hideEdgesOnViewport?: boolean;
    textureOnViewport?: boolean;
    motionBlur?: boolean;
    motionBlurOpacity?: number;
    pixelRatio?: number;
  }

  const CytoscapeComponent: ComponentType<CytoscapeComponentProps>;
  export default CytoscapeComponent;
}
