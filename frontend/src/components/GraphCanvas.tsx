import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import type Cytoscape from 'cytoscape';
type CyStylesheet = Cytoscape.StylesheetCSS;
import { Input, Button, Spin, message, Select, Switch, Tag } from 'antd';
import {
  SearchOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  ExpandOutlined,
  ApartmentOutlined,
  ReloadOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  RightOutlined,
  DownOutlined,
  StarFilled,
  StarOutlined,
  LoadingOutlined,
  FilterOutlined,
  BranchesOutlined,
  VerticalAlignMiddleOutlined,
} from '@ant-design/icons';
import type { GraphData, GraphNode, GraphEdge } from '../types';

/* ============================================================
   Constants
   ============================================================ */

type ViewMode = 'structure' | 'all' | 'essence' | 'cross';
type LayoutMode = 'tree' | 'lane' | 'network';

interface Props {
  graphData: GraphData | null;
  loading: boolean;
  showIntegrated: boolean;
  onNodeClick: (node: GraphNode) => void;
  onToggleView: () => void;
  textbookId: string | null;
}

// 10 distinct colors for different textbooks
const BOOK_COLORS = [
  '#FF6B6B', // Coral Red
  '#4ECDC4', // Teal
  '#45B7D1', // Sky Blue
  '#96CEB4', // Sage Green
  '#FFD93D', // Gold
  '#C084FC', // Purple
  '#FB923C', // Orange
  '#F472B6', // Pink
  '#34D399', // Emerald
  '#60A5FA', // Blue
];

function getBookColor(bookId: string): string {
  let hash = 0;
  for (let i = 0; i < bookId.length; i++) {
    hash = (hash << 5) - hash + bookId.charCodeAt(i);
    hash |= 0;
  }
  return BOOK_COLORS[Math.abs(hash) % BOOK_COLORS.length];
}

const BOOK_NAMES: Record<string, string> = {
  medicine: '内科学',
  surgery: '外科学',
  pediatrics: '儿科学',
  obgyn: '妇产科学',
  neurology: '神经病学',
  pharmacology: '药理学',
  pathology: '病理学',
};

function getBookName(bookId: string): string {
  return BOOK_NAMES[bookId] || bookId;
}

function getGranularityLabel(granularity?: string): string {
  const labels: Record<string, string> = {
    chapter_topic: '章节主题',
    section_topic: '大类',
    core_concept: '核心概念',
    detail_fact: '细节事实',
  };
  return granularity ? labels[granularity] || granularity : '未分类';
}

function getEdgeTypeLabel(relationType: string): string {
  const labels: Record<string, string> = {
    contains: '包含',
    prerequisite: '前置',
    parallel: '平行',
    applies_to: '适用',
    cross_textbook: '跨教材',
  };
  return labels[relationType] || relationType;
}

const EDGE_TYPE_DISPLAY_COLORS: Record<string, string> = {
  contains: '#4ECDC4',
  prerequisite: '#FFD93D',
  parallel: '#999',
  applies_to: '#2ECC71',
  cross_textbook: '#FFD700',
};

/* ============================================================
   Helper: find all descendants via contains edges
   ============================================================ */

function getDescendants(nodeId: string, edges: GraphEdge[]): string[] {
  const directChildren = edges
    .filter((e) => e.relation_type === 'contains' && e.source === nodeId)
    .map((e) => e.target);
  const allDescendants = [...directChildren];
  for (const childId of directChildren) {
    const grandChildren = getDescendants(childId, edges);
    allDescendants.push(...grandChildren);
  }
  return [...new Set(allDescendants)];
}

/* ============================================================
   Helper: dagre-like hierarchical layout using preset positions
   ============================================================ */

function computeHierarchicalPositions(
  nodes: GraphNode[],
  edges: GraphEdge[]
): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};

  // Build parent->children map from contains edges
  const childrenOf = new Map<string, string[]>();
  edges.forEach((e) => {
    if (e.relation_type === 'contains') {
      if (!childrenOf.has(e.source)) childrenOf.set(e.source, []);
      childrenOf.get(e.source)!.push(e.target);
    }
  });

  const Y_LEVEL: Record<string, number> = {
    chapter_topic: 0,
    section_topic: 200,
    core_concept: 400,
    detail_fact: 580,
  };

  const Y_DEFAULT = 0;
  const LEAF_WIDTH = 200;

  // Determine Y based on granularity
  function getY(granularity?: string): number {
    return granularity && Y_LEVEL[granularity] !== undefined
      ? Y_LEVEL[granularity]
      : Y_DEFAULT;
  }

  // Count leaf nodes under a given node (nodes with no contains-children)
  function leafCount(nodeId: string): number {
    const children = childrenOf.get(nodeId) || [];
    if (children.length === 0) return 1;
    return children.reduce((sum, c) => sum + leafCount(c), 0);
  }

  // Recursively position nodes. Returns [xStart, xEnd] of the subtree.
  function positionSubtree(
    nodeId: string,
    depth: number,
    xOffset: number
  ): [number, number] {
    const children = childrenOf.get(nodeId) || [];
    const node = nodes.find((n) => n.id === nodeId);
    const y = node ? getY(node.granularity) : depth * 200;

    if (children.length === 0) {
      // Leaf node
      positions[nodeId] = { x: xOffset + LEAF_WIDTH / 2, y };
      return [xOffset, xOffset + LEAF_WIDTH];
    }

    // Position children first
    const childRanges: [number, number][] = [];
    let childX = xOffset;
    for (const childId of children) {
      const range = positionSubtree(childId, depth + 1, childX);
      childRanges.push(range);
      childX = range[1];
    }

    // Position this node at the center of its children's total x-range
    const totalStart = childRanges[0][0];
    const totalEnd = childRanges[childRanges.length - 1][1];
    const parentX = (totalStart + totalEnd) / 2;
    const parentY = node ? getY(node.granularity) : depth * 200;
    positions[nodeId] = { x: parentX, y: parentY };

    return [totalStart, totalEnd];
  }

  // Identify root nodes: those without a "contains" parent
  const allChildren = new Set(
    edges
      .filter((e) => e.relation_type === 'contains')
      .map((e) => e.target)
  );
  const rootIds = nodes
    .filter((n) => !allChildren.has(n.id))
    .map((n) => n.id);

  // Layout each root tree
  let overallX = 50;
  for (const rootId of rootIds) {
    const range = positionSubtree(rootId, 0, overallX);
    overallX = range[1] + LEAF_WIDTH; // Gap between root trees
  }

  // Handle orphan nodes (not in any contains relationship)
  nodes.forEach((n) => {
    if (positions[n.id]) return;
    positions[n.id] = {
      x: overallX + LEAF_WIDTH / 2,
      y: getY(n.granularity),
    };
    overallX += LEAF_WIDTH;
  });

  return positions;
}

/* ============================================================
   Helper: render importance stars as React fragments
   ============================================================ */

function ImportanceStars({ value }: { value: number }): React.ReactElement {
  const count = Math.round(Math.min(Math.max(value, 0), 5));
  return (
    <>
      {Array.from({ length: 5 }, (_, i) =>
        i < count ? (
          <StarFilled key={i} style={{ color: '#FFD93D', fontSize: 11 }} />
        ) : (
          <StarOutlined key={i} style={{ color: '#555', fontSize: 11 }} />
        )
      )}
    </>
  );
}

/* ============================================================
   Cytoscape Stylesheet
   ============================================================ */

const cytoscapeStylesheet: CyStylesheet[] = [
  // ---- Base Node ----
  {
    selector: 'node',
    css: {
      'background-color': 'data(color)',
      label: 'data(label)',
      color: '#fff',
      'font-size': '10px',
      'text-wrap': 'wrap',
      'text-max-width': '100px',
      'text-valign': 'center',
      'text-halign': 'center',
      'text-background-color': 'rgba(0,0,0,0.55)',
      'text-background-opacity': 1,
      'text-background-padding': '4px',
      'text-background-shape': 'roundrectangle',
      'border-color': 'transparent',
      'border-width': 0,
      'border-style': 'solid',
      'transition-property': 'border-color border-width',
      'transition-duration': 200,
      'min-zoomed-font-size': 6,
    },
  },

  // ---- Chapter Topic: large rounded rectangle, bold label ----
  {
    selector: 'node[granularity = "chapter_topic"]',
    css: {
      'background-color': 'data(color)',
      shape: 'round-rectangle',
      width: 200,
      height: 40,
      'font-weight': 'bold',
      'font-size': '12px',
      'border-color': 'data(color)',
      'border-width': 2,
      'border-opacity': 0.9,
      'text-background-color': 'rgba(0,0,0,0.6)',
    },
  },

  // ---- Section Topic: medium rounded rectangle, slightly transparent ----
  {
    selector: 'node[granularity = "section_topic"]',
    css: {
      shape: 'round-rectangle',
      width: 160,
      height: 36,
      'font-size': '10px',
      'background-opacity': 0.75,
      'border-color': 'data(color)',
      'border-width': 1.5,
      'border-opacity': 0.5,
      'text-background-color': 'rgba(0,0,0,0.5)',
    },
  },

  // ---- Core Concept: ellipse, size by importance ----
  {
    selector: 'node[granularity = "core_concept"]',
    css: {
      shape: 'ellipse',
      width: 'mapData(importance, 0, 5, 28, 60)',
      height: 'mapData(importance, 0, 5, 28, 60)',
      'font-size': '9px',
    },
  },

  // ---- Merged nodes: double white border ----
  {
    selector: 'node[?merged]',
    css: {
      'border-color': '#fff',
      'border-width': 3,
      'border-style': 'double',
      'border-opacity': 0.9,
    },
  },

  // ---- Teacher-locked: dashed purple border ----
  {
    selector: 'node[?teacher_locked]',
    css: {
      'border-color': '#C084FC',
      'border-width': 2,
      'border-style': 'dashed',
    },
  },

  // ---- Low quality (quality_score < 0.65): yellow warning border ----
  {
    selector: 'node[quality_score < 0.65]',
    css: {
      'border-color': '#FFD93D',
      'border-width': 3,
      'border-style': 'solid',
      'border-opacity': 0.85,
    },
  },

  // ---- Selected node ----
  {
    selector: 'node:selected',
    css: {
      'border-color': '#4ECDC4',
      'border-width': 3,
      'border-opacity': 1,
    },
  },

  // ---- Base Edge ----
  {
    selector: 'edge',
    css: {
      width: 'mapData(weight, 0, 10, 0.5, 4)',
      'line-color': '#666',
      'target-arrow-color': '#666',
      'target-arrow-shape': 'triangle-backcurve',
      'curve-style': 'bezier',
      opacity: 0.5,
      label: 'data(label)',
      'font-size': '8px',
      color: '#ccc',
      'text-background-color': '#1a1a2e',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
      'edge-text-rotation': 'autorotate',
      'min-zoomed-font-size': 5,
    } as any,
  },

  // ---- Contains: light blue ----
  {
    selector: 'edge.contains',
    css: {
      'line-color': '#4ECDC4',
      'target-arrow-color': '#4ECDC4',
      'curve-style': 'bezier',
      opacity: 0.6,
    },
  },

  // ---- Prerequisite: orange ----
  {
    selector: 'edge.prerequisite',
    css: {
      'line-color': '#FFD93D',
      'target-arrow-color': '#FFD93D',
      opacity: 0.7,
    },
  },

  // ---- Parallel: gray ----
  {
    selector: 'edge.parallel',
    css: {
      'line-color': '#999',
      'target-arrow-color': '#999',
      opacity: 0.5,
    },
  },

  // ---- Applies_to: green ----
  {
    selector: 'edge.applies_to',
    css: {
      'line-color': '#2ECC71',
      'target-arrow-color': '#2ECC71',
      opacity: 0.6,
    },
  },

  // ---- Cross-textbook: bright gold, thicker, haystack straight line ----
  {
    selector: 'edge.cross-textbook',
    css: {
      'line-color': '#FFD700',
      'target-arrow-color': '#FFD700',
      width: 'mapData(weight, 0, 10, 2, 6)',
      'curve-style': 'haystack',
      'haystack-radius': 0.5,
      opacity: 0.85,
    },
  },

  // ---- Edge selected ----
  {
    selector: 'edge:selected',
    css: {
      'line-color': '#4ECDC4',
      'target-arrow-color': '#4ECDC4',
      opacity: 1,
    },
  },
];

/* ============================================================
   Layout Options
   ============================================================ */

const LAYOUT_MODE_LABELS: Record<LayoutMode, string> = {
  tree: '分层布局',
  lane: '树形布局',
  network: '网络布局',
};

function computeLayoutOptions(mode: LayoutMode, data: GraphData | null) {
  if (!data) return { name: 'null' };

  switch (mode) {
    case 'tree': {
      const positions = computeHierarchicalPositions(data.nodes, data.edges);
      return {
        name: 'preset' as const,
        positions: (node: any) => positions[node.id()] || { x: 0, y: 0 },
        animate: false,
        fit: true,
        padding: 50,
      };
    }
    case 'lane': {
      return {
        name: 'breadthfirst' as const,
        directed: true,
        spacingFactor: 1.5,
        animate: true,
        fit: true,
        padding: 50,
      };
    }
    case 'network':
    default:
      return {
        name: 'cose' as const,
        animate: true,
        animationDuration: 500,
        nodeRepulsion: () => 10000,
        idealEdgeLength: (edge: any) => 120,
        gravity: 0.25,
        numIter: 1000,
        componentSpacing: 180,
        nodeOverlap: 15,
        padding: 50,
        refresh: 20,
        fit: true,
      };
  }
}

/* ============================================================
   View Mode Constants
   ============================================================ */

const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  structure: '结构视图',
  all: '全部核心',
  essence: '精华视图',
  cross: '跨教材关系',
};

const VIEW_MODE_DESC: Record<ViewMode, string> = {
  structure: '仅显示章节主题和大类',
  all: '显示所有知识点',
  essence: '仅显示精华概念',
  cross: '显示跨教材关系边',
};

/* ============================================================
   GraphCanvas Component
   ============================================================ */

const GraphCanvas: React.FC<Props> = ({
  graphData,
  loading,
  showIntegrated,
  onNodeClick,
  onToggleView,
  textbookId,
}) => {
  const cyRef = useRef<Cytoscape.Core | null>(null);
  const graphDataRef = useRef(graphData);
  const onNodeClickRef = useRef(onNodeClick);
  const minimapCanvasRef = useRef<HTMLCanvasElement>(null);
  const searchAnimationRef = useRef<number | null>(null);
  const pulseHighlightRef = useRef<number | null>(null);

  // ---- State ----
  const [searchText, setSearchText] = useState('');
  const [selectedRelationTypes, setSelectedRelationTypes] = useState<string[]>([]);
  const [selectedTextbooks, setSelectedTextbooks] = useState<string[]>([]);
  const [legendItems, setLegendItems] = useState<
    { id: string; name: string; color: string }[]
  >([]);
  const [viewMode, setViewMode] = useState<ViewMode>('structure');
  const [granularityFilter, setGranularityFilter] = useState<string[]>([]);
  const [foldDetail, setFoldDetail] = useState(true);
  const [crossTextbookOnly, setCrossTextbookOnly] = useState(false);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(
    showIntegrated ? 'lane' : 'tree'
  );
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const [legendCollapsed, setLegendCollapsed] = useState(false);

  // Tooltip state
  const [tooltipState, setTooltipState] = useState<{
    visible: boolean;
    x: number;
    y: number;
    node: GraphNode | null;
  }>({ visible: false, x: 0, y: 0, node: null });

  // ---- Keep refs fresh ----
  useEffect(() => {
    graphDataRef.current = graphData;
  }, [graphData]);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  // ---- Reset layout mode on view switch ----
  useEffect(() => {
    setLayoutMode(showIntegrated ? 'lane' : 'tree');
  }, [showIntegrated]);

  // ---- Reset collapsed state on data change ----
  useEffect(() => {
    setCollapsedIds(new Set());
  }, [graphData]);

  // ---- Cleanup search animation on unmount ----
  useEffect(() => {
    return () => {
      if (searchAnimationRef.current) {
        clearInterval(searchAnimationRef.current);
      }
      if (pulseHighlightRef.current) {
        clearInterval(pulseHighlightRef.current);
      }
    };
  }, []);

  // ---- Build legend from data ----
  useEffect(() => {
    if (!graphData) {
      setLegendItems([]);
      return;
    }
    const bookIds = [...new Set(graphData.nodes.map((n) => n.textbook))];
    setLegendItems(
      bookIds.map((id) => ({
        id,
        name: BOOK_NAMES[id] || id,
        color: getBookColor(id),
      }))
    );
  }, [graphData]);

  // ---- Compute available relation types ----
  const relationTypes = useMemo(() => {
    if (!graphData) return [];
    return [...new Set(graphData.edges.map((e) => e.relation_type))];
  }, [graphData]);

  // ---- Compute available granularities ----
  const availableGranularities = useMemo(() => {
    if (!graphData) return [];
    return [
      ...new Set(graphData.nodes.map((n) => n.granularity).filter(Boolean)),
    ] as string[];
  }, [graphData]);

  // ---- Toggle textbook filter ----
  const toggleTextbook = useCallback((id: string) => {
    setSelectedTextbooks((prev) => {
      if (prev.includes(id)) return prev.filter((t) => t !== id);
      return [...prev, id];
    });
  }, []);

  // ---- Filter callbacks ----
  const passesGranularityFilter = useCallback(
    (node: GraphNode): boolean => {
      if (granularityFilter.length === 0) return true;
      return node.granularity
        ? granularityFilter.includes(node.granularity)
        : false;
    },
    [granularityFilter]
  );

  const passesViewMode = useCallback(
    (node: GraphNode): boolean => {
      switch (viewMode) {
        case 'structure':
          return (
            node.granularity === 'chapter_topic' ||
            node.granularity === 'section_topic' ||
            !node.granularity
          );
        case 'all':
          return true;
        case 'essence':
          return node.is_essence === true;
        case 'cross':
          return true;
        default:
          return true;
      }
    },
    [viewMode]
  );

  const passesFoldFilter = useCallback(
    (node: GraphNode): boolean => {
      if (!foldDetail) return true;
      return node.granularity !== 'detail_fact';
    },
    [foldDetail]
  );

  // ---- Compute elements with expand/collapse support ----
  const elements = useMemo(() => {
    if (!graphData) return [];

    // If some nodes are collapsed, find all descendants to hide
    const hiddenIds = new Set<string>();
    if (collapsedIds.size > 0) {
      for (const collapsedId of collapsedIds) {
        const descendants = getDescendants(collapsedId, graphData.edges);
        descendants.forEach((d) => hiddenIds.add(d));
      }
    }

    // Filter nodes
    let filteredNodes = graphData.nodes;
    if (selectedTextbooks.length > 0) {
      filteredNodes = filteredNodes.filter((n) =>
        selectedTextbooks.includes(n.textbook)
      );
    }
    filteredNodes = filteredNodes.filter(passesViewMode);
    filteredNodes = filteredNodes.filter(passesGranularityFilter);
    filteredNodes = filteredNodes.filter(passesFoldFilter);
    // Remove collapsed/hidden nodes
    filteredNodes = filteredNodes.filter((n) => !hiddenIds.has(n.id));

    const visibleNodeIds = new Set(filteredNodes.map((n) => n.id));

    // Build textbook map
    const nodeTextbookMap = new Map<string, string>();
    graphData.nodes.forEach((n) => {
      nodeTextbookMap.set(n.id, n.textbook);
    });

    // Filter edges
    let filteredEdges = graphData.edges;
    if (selectedRelationTypes.length > 0) {
      filteredEdges = filteredEdges.filter((e) =>
        selectedRelationTypes.includes(e.relation_type)
      );
    }
    if (viewMode === 'cross') {
      filteredEdges = filteredEdges.filter((e) => {
        const src = nodeTextbookMap.get(e.source);
        const tgt = nodeTextbookMap.get(e.target);
        return src && tgt && src !== tgt;
      });
    }
    if (crossTextbookOnly) {
      filteredEdges = filteredEdges.filter((e) => {
        const src = nodeTextbookMap.get(e.source);
        const tgt = nodeTextbookMap.get(e.target);
        return src && tgt && src !== tgt;
      });
    }
    filteredEdges = filteredEdges.filter(
      (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );

    // Build node elements
    const nodes = filteredNodes.map((n) => {
      const classes: string[] = [];
      if (n.is_merged) classes.push('merged');

      return {
        data: {
          id: n.id,
          label: n.label,
          definition: n.definition || '',
          category: n.category || '',
          importance: n.importance || 1,
          type: n.category,
          source_book: n.textbook,
          frequency: n.frequency || 1,
          merged: n.is_merged,
          confidence: n.importance ? n.importance / 5 : 0.5,
          teacher_locked: n.teacher_locked,
          chapters: n.chapter ? [n.chapter] : [],
          color: n.color || getBookColor(n.textbook),
          granularity: n.granularity || '',
          is_essence: n.is_essence || false,
          created_by: n.created_by || '',
          display_level:
            n.display_level != null ? String(n.display_level) : '',
          parent_id: n.parent_id || '',
          node_role: n.node_role || '',
          quality_score: n.quality_score ?? 1,
        },
        classes: classes.join(' '),
      };
    });

    // Build edge elements
    const edges = filteredEdges.map((e) => {
      const classes: string[] = [];
      if (e.relation_type === 'contains') classes.push('contains');
      if (e.relation_type === 'prerequisite') classes.push('prerequisite');
      if (e.relation_type === 'parallel') classes.push('parallel');
      if (e.relation_type === 'applies_to') classes.push('applies_to');

      const srcTextbook = nodeTextbookMap.get(e.source);
      const tgtTextbook = nodeTextbookMap.get(e.target);
      const isCrossTextbook =
        srcTextbook && tgtTextbook && srcTextbook !== tgtTextbook;
      if (isCrossTextbook) classes.push('cross-textbook');

      return {
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          label:
            e.relation_type === 'contains'
              ? '包含'
              : e.relation_type === 'prerequisite'
                ? '前置'
                : e.relation_type === 'parallel'
                  ? '平行'
                  : e.relation_type === 'applies_to'
                    ? '适用'
                    : e.relation_type,
          weight: e.confidence * 10,
          relation_type: e.relation_type,
          relation_subtype: e.relation_subtype || '',
          is_cross_textbook: e.is_cross_textbook || false,
        },
        classes: classes.join(' '),
      };
    });

    return [...nodes, ...edges];
  }, [
    graphData,
    collapsedIds,
    selectedTextbooks,
    selectedRelationTypes,
    viewMode,
    granularityFilter,
    foldDetail,
    crossTextbookOnly,
    passesViewMode,
    passesGranularityFilter,
    passesFoldFilter,
  ]);

  // ---- Compute layout options ----
  const layoutOptions = useMemo(
    () => computeLayoutOptions(layoutMode, graphData),
    [layoutMode, graphData]
  );

  // ---- Minimap update effect (must be after elements and layoutOptions) ----
  useEffect(() => {
    const cy = cyRef.current;
    const canvas = minimapCanvasRef.current;
    if (!cy || !canvas) return;

    function drawMinimap() {
      const curCanvas = minimapCanvasRef.current;
      const curCy = cyRef.current;
      if (!curCanvas || !curCy) return;
      const ctx = curCanvas.getContext('2d');
      if (!ctx) return;

      const width = curCanvas.width;
      const height = curCanvas.height;
      ctx.clearRect(0, 0, width, height);

      // Background
      ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
      ctx.fillRect(0, 0, width, height);

      const graphEles = curCy.elements();
      if (graphEles.length === 0) return;

      const bb = graphEles.boundingBox();
      if (bb.w === 0 || bb.h === 0) return;

      const pad = 6;
      const availW = width - 2 * pad;
      const availH = height - 2 * pad;
      const scale = Math.min(availW / bb.w, availH / bb.h);
      const cx = bb.x1 + bb.w / 2;
      const cyc = bb.y1 + bb.h / 2;

      function toMinimap(wx: number, wy: number): [number, number] {
        return [
          (wx - cx) * scale + width / 2,
          (wy - cyc) * scale + height / 2,
        ];
      }

      // Draw edges
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.lineWidth = 0.5;
      curCy.edges().forEach((e) => {
        const src = e.source().position();
        const tgt = e.target().position();
        const [x1, y1] = toMinimap(src.x, src.y);
        const [x2, y2] = toMinimap(tgt.x, tgt.y);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      });

      // Draw nodes
      curCy.nodes().forEach((n) => {
        const pos = n.position();
        const [mx, my] = toMinimap(pos.x, pos.y);
        const color = n.data('color') || '#888';
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(mx, my, 2, 0, Math.PI * 2);
        ctx.fill();
      });

      // Draw viewport
      const pan = curCy.pan();
      const zoom = curCy.zoom();
      const vpLeft = -pan.x / zoom;
      const vpTop = -pan.y / zoom;
      const vpRight = vpLeft + (curCy.width() / zoom) * 0.95;
      const vpBottom = vpTop + (curCy.height() / zoom) * 0.95;
      const [vx1, vy1] = toMinimap(vpLeft, vpTop);
      const [vx2, vy2] = toMinimap(vpRight, vpBottom);

      ctx.strokeStyle = '#4ECDC4';
      ctx.lineWidth = 1.2;
      ctx.strokeRect(vx1, vy1, vx2 - vx1, vy2 - vy1);

      // Subtle overlay outside viewport
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(0, 0, width, vy1);
      ctx.fillRect(0, vy2, width, height - vy2);
      ctx.fillRect(0, vy1, vx1, vy2 - vy1);
      ctx.fillRect(vx2, vy1, width - vx2, vy2 - vy1);
    }

    drawMinimap();

    cy.on('pan zoom position add remove', drawMinimap);
    return () => {
      cy.removeListener('pan', drawMinimap);
      cy.removeListener('zoom', drawMinimap);
      cy.removeListener('position', drawMinimap);
      cy.removeListener('add', drawMinimap);
      cy.removeListener('remove', drawMinimap);
    };
  }, [elements, layoutOptions]);

  // ---- Node click handler (expand/collapse + detail) ----
  const handleNodeClick = useCallback((evt: any) => {
    const node = evt.target;
    const nodeData = node.data();
    if (!nodeData || !nodeData.id) return;

    // Toggle expand/collapse for chapter_topic and section_topic
    const granularity: string = nodeData.granularity || '';
    if (
      granularity === 'chapter_topic' ||
      granularity === 'section_topic'
    ) {
      setCollapsedIds((prev) => {
        const next = new Set(prev);
        if (next.has(nodeData.id)) {
          next.delete(nodeData.id);
        } else {
          next.add(nodeData.id);
        }
        return next;
      });
    }

    // Open detail drawer
    const data = graphDataRef.current;
    if (!data) return;
    const origNode = data.nodes.find((n: GraphNode) => n.id === nodeData.id);
    if (origNode) onNodeClickRef.current(origNode);
  }, []);

  // ---- Cytoscape initialization ----
  const handleCyInit = useCallback(
    (cy: Cytoscape.Core) => {
      cyRef.current = cy;

      // Node click
      cy.on('tap', 'node', handleNodeClick);

      // Hover tooltip
      cy.on('mouseover', 'node', (evt) => {
        const nodeId = evt.target.data('id');
        const data = graphDataRef.current;
        if (!data) return;
        const origNode = data.nodes.find(
          (n: GraphNode) => n.id === nodeId
        );
        if (!origNode) return;

        const container = cy.container();
        if (!container) return;
        const containerRect = container.getBoundingClientRect();
        const mouseEvt = evt.originalEvent as MouseEvent;
        setTooltipState({
          visible: true,
          x: mouseEvt.clientX - containerRect.left,
          y: mouseEvt.clientY - containerRect.top,
          node: origNode,
        });
      });

      cy.on('mousemove', 'node', (evt) => {
        const container = cy.container();
        if (!container) return;
        const containerRect = container.getBoundingClientRect();
        const mouseEvt = evt.originalEvent as MouseEvent;
        setTooltipState((prev) => {
          if (!prev.visible) return prev;
          return {
            ...prev,
            x: mouseEvt.clientX - containerRect.left,
            y: mouseEvt.clientY - containerRect.top,
          };
        });
      });

      cy.on('mouseout', 'node', () => {
        setTooltipState((prev) => ({ ...prev, visible: false }));
      });
    },
    [handleNodeClick]
  );

  // ---- Search handler with pulsing animation ----
  const handleSearch = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Clear previous animation
    if (pulseHighlightRef.current) {
      clearInterval(pulseHighlightRef.current);
      pulseHighlightRef.current = null;
    }

    // Reset all nodes
    cy.nodes().style({
      'border-color': '',
      'border-width': '',
    });

    const query = searchText.trim();
    if (!query) return;

    const matching = cy.nodes().filter((n) => {
      const label = n.data('label') || '';
      return label.toLowerCase().includes(query.toLowerCase());
    });

    if (matching.length > 0) {
      // Highlight
      matching.style({
        'border-color': '#FFD93D',
        'border-width': 4,
      });

      // Pulse animation
      let toggle = true;
      pulseHighlightRef.current = window.setInterval(() => {
        matching.style({
          'border-color': toggle ? '#FFD93D' : '#FF8C00',
          'border-width': toggle ? '4' : '2',
        });
        toggle = !toggle;
      }, 600);

      // Fit view
      cy.animate({
        fit: { eles: matching, padding: 80 },
        duration: 400,
      });

      message.success(`找到 ${matching.length} 个匹配节点`);
    } else {
      message.info('未找到匹配的节点');
    }
  }, [searchText]);

  // ---- Reset search ----
  const handleResetSearch = useCallback(() => {
    setSearchText('');
    const cy = cyRef.current;
    if (cy) {
      if (pulseHighlightRef.current) {
        clearInterval(pulseHighlightRef.current);
        pulseHighlightRef.current = null;
      }
      cy.nodes().style({ 'border-color': '', 'border-width': '' });
      cy.fit(undefined, 50);
    }
  }, []);

  // ---- Zoom controls ----
  const handleZoomIn = useCallback(() => {
    const cy = cyRef.current;
    if (cy) cy.zoom(cy.zoom() * 1.3);
  }, []);

  const handleZoomOut = useCallback(() => {
    const cy = cyRef.current;
    if (cy) cy.zoom(cy.zoom() / 1.3);
  }, []);

  const handleFit = useCallback(() => {
    const cy = cyRef.current;
    if (cy) cy.fit(undefined, 50);
  }, []);

  // ---- Minimap click handler ----
  const handleMinimapClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const cy = cyRef.current;
      const canvas = minimapCanvasRef.current;
      if (!cy || !canvas) return;

      const rect = canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      const elements = cy.elements();
      if (elements.length === 0) return;
      const bb = elements.boundingBox();
      if (bb.w === 0 || bb.h === 0) return;

      const pad = 6;
      const availW = canvas.width - 2 * pad;
      const availH = canvas.height - 2 * pad;
      const scale = Math.min(availW / bb.w, availH / bb.h);
      const cx = bb.x1 + bb.w / 2;
      const cyc = bb.y1 + bb.h / 2;

      // Convert minimap coordinates to world coordinates
      const wx = (clickX - canvas.width / 2) / scale + cx;
      const wy = (clickY - canvas.height / 2) / scale + cyc;

      const zoom = cy.zoom();
      cy.animate({
        pan: {
          x: -wx * zoom + cy.width() / 2,
          y: -wy * zoom + cy.height() / 2,
        },
        duration: 200,
      });
    },
    []
  );

  // ---- Counts ----
  const currentNodeCount = elements.filter((e: any) => !e.data.source).length;
  const currentEdgeCount = elements.filter((e: any) => e.data.source).length;

  // ---- Edge types present in data (for legend) ----
  const edgeTypesPresent = useMemo(() => {
    if (!graphData) return [];
    const types = [...new Set(graphData.edges.map((e) => e.relation_type))];
    return types.filter((t) => EDGE_TYPE_DISPLAY_COLORS[t] !== undefined);
  }, [graphData]);

  // ---- Determine if a node has children (for expand/collapse icon) ----
  const hasChildren = useCallback(
    (nodeId: string): boolean => {
      if (!graphData) return false;
      return graphData.edges.some(
        (e) => e.relation_type === 'contains' && e.source === nodeId
      );
    },
    [graphData]
  );

  // Extract for safe JSX usage
  const tooltipNode = tooltipState.node;

  /* ============================================================
     Render
     ============================================================ */

  return (
    <div className="center-panel">
      {/* Search bar + Filters */}
      <div className="graph-search">
        <Input.Search
          placeholder="搜索概念节点..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onSearch={handleSearch}
          onPressEnter={() => handleSearch()}
          style={{ background: 'rgba(255,255,255,0.08)', borderRadius: 6 }}
          size="small"
        />

        {/* View Mode Selector */}
        <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Select
            value={viewMode}
            onChange={(val: ViewMode) => setViewMode(val)}
            style={{ minWidth: 110, fontSize: 12 }}
            size="small"
            dropdownMatchSelectWidth={false}
          >
            {(Object.entries(VIEW_MODE_LABELS) as [ViewMode, string][]).map(
              ([key, label]) => (
                <Select.Option key={key} value={key}>
                  {label}
                </Select.Option>
              )
            )}
          </Select>

          {/* Granularity filter */}
          {availableGranularities.length > 0 && (
            <Select
              mode="multiple"
              placeholder="粒度筛选"
              value={granularityFilter}
              onChange={setGranularityFilter}
              style={{ minWidth: 130, fontSize: 12 }}
              size="small"
              allowClear
              notFoundContent="无"
            >
              {availableGranularities.map((g) => (
                <Select.Option key={g} value={g}>
                  {getGranularityLabel(g)}
                </Select.Option>
              ))}
            </Select>
          )}
        </div>

        <div
          style={{
            marginTop: 4,
            display: 'flex',
            gap: 4,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <Select
            mode="multiple"
            placeholder="关系类型筛选"
            value={selectedRelationTypes}
            onChange={setSelectedRelationTypes}
            style={{ minWidth: 140, fontSize: 12 }}
            size="small"
            allowClear
            notFoundContent="无不匹配类型"
          >
            {relationTypes.map((rt) => (
              <Select.Option key={rt} value={rt}>
                {getEdgeTypeLabel(rt)}
              </Select.Option>
            ))}
          </Select>

          {selectedTextbooks.length > 0 && (
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => setSelectedTextbooks([])}
              style={{ color: '#4ECDC4', borderColor: '#4ECDC4', fontSize: 11 }}
            >
              全部教材
            </Button>
          )}
        </div>

        {/* Toggles row */}
        <div
          style={{
            marginTop: 4,
            display: 'flex',
            gap: 8,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: '#aaa',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <VerticalAlignMiddleOutlined />
            <span>折叠详情</span>
            <Switch
              size="small"
              checked={foldDetail}
              onChange={setFoldDetail}
              style={{ marginLeft: 2 }}
            />
          </span>
          <span
            style={{
              fontSize: 11,
              color: '#aaa',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <BranchesOutlined />
            <span>只看跨教材</span>
            <Switch
              size="small"
              checked={crossTextbookOnly}
              onChange={setCrossTextbookOnly}
              style={{ marginLeft: 2 }}
            />
          </span>
        </div>
      </div>

      {/* Toolbar */}
      <div className="graph-toolbar">
        <Button
          size="small"
          icon={<ZoomInOutlined />}
          onClick={handleZoomIn}
          title="放大"
        />
        <Button
          size="small"
          icon={<ZoomOutOutlined />}
          onClick={handleZoomOut}
          title="缩小"
        />
        <Button
          size="small"
          icon={<ExpandOutlined />}
          onClick={handleFit}
          title="适应屏幕"
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={handleResetSearch}
          title="重置搜索"
        />

        <Select
          value={layoutMode}
          onChange={(val: LayoutMode) => setLayoutMode(val)}
          size="small"
          style={{ minWidth: 90, fontSize: 12 }}
          dropdownMatchSelectWidth={false}
        >
          {(Object.entries(LAYOUT_MODE_LABELS) as [LayoutMode, string][]).map(
            ([key, label]) => (
              <Select.Option key={key} value={key}>
                {label}
              </Select.Option>
            )
          )}
        </Select>

        <Button
          size="small"
          type={showIntegrated ? 'primary' : 'default'}
          icon={<ApartmentOutlined />}
          onClick={onToggleView}
          style={
            showIntegrated
              ? { background: '#4ECDC4', borderColor: '#4ECDC4' }
              : {}
          }
        >
          {showIntegrated ? '整合图' : '单本图'}
        </Button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="graph-loading">
          <Spin indicator={<LoadingOutlined style={{ fontSize: 32 }} spin />} />
          <span style={{ marginTop: 8, color: '#aaa', fontSize: 14 }}>
            加载知识图谱...
          </span>
        </div>
      )}

      {/* Empty state: no data loaded */}
      {!loading && !graphData && (
        <div className="graph-empty">
          <div className="graph-empty-icon-wrapper">
            <ApartmentOutlined className="graph-empty-icon" />
            <div className="graph-empty-ring" />
          </div>
          <span className="graph-empty-title">请选择教材</span>
          <span className="graph-empty-desc">
            选择左侧教材以加载知识图谱，或使用「整合」功能查看多教材图谱
          </span>
        </div>
      )}

      {/* Empty state: data loaded but no nodes */}
      {!loading && graphData && graphData.nodes.length === 0 && (
        <div className="graph-empty">
          <div className="graph-empty-icon-wrapper">
            <ApartmentOutlined className="graph-empty-icon" />
            <div className="graph-empty-ring" />
          </div>
          <span className="graph-empty-title">该教材暂无图谱数据</span>
          <span className="graph-empty-desc">
            请确认教材已成功解析并提取知识图谱
          </span>
        </div>
      )}

      {/* Empty state: filters resulted in no visible elements */}
      {!loading &&
        graphData &&
        graphData.nodes.length > 0 &&
        elements.length === 0 && (
          <div className="graph-empty">
            <div className="graph-empty-icon-wrapper">
              <FilterOutlined className="graph-empty-icon" />
              <div className="graph-empty-ring" />
            </div>
            <span className="graph-empty-title">筛选后无可见节点</span>
            <span className="graph-empty-desc">
              尝试调整筛选条件以显示更多内容
            </span>
            <Button
              size="small"
              onClick={() => {
                setSelectedRelationTypes([]);
                setSelectedTextbooks([]);
                setGranularityFilter([]);
                setCollapsedIds(new Set());
              }}
              style={{ marginTop: 8 }}
            >
              重置所有筛选
            </Button>
          </div>
        )}

      {/* Graph canvas */}
      {!loading &&
        graphData &&
        graphData.nodes.length > 0 &&
        elements.length > 0 && (
          <CytoscapeComponent
            key={
              showIntegrated
                ? 'integrated'
                : `single-${textbookId || 'none'}`
            }
            elements={elements}
            style={{
              width: '100%',
              height: '100%',
              background: '#0f0c29',
            }}
            stylesheet={cytoscapeStylesheet}
            layout={layoutOptions}
            cy={handleCyInit}
            wheelSensitivity={0.4}
            minZoom={0.15}
            maxZoom={5}
            autoungrabify={false}
            autounselectify={false}
            boxSelectionEnabled={false}
          />
        )}

      {/* --- Minimap --- */}
      {!loading &&
        graphData &&
        graphData.nodes.length > 0 &&
        elements.length > 0 && (
          <div className="graph-minimap">
            <canvas
              ref={minimapCanvasRef}
              width={160}
              height={120}
              className="graph-minimap-canvas"
              onClick={handleMinimapClick}
            />
          </div>
        )}

      {/* --- Hover Tooltip --- */}
      {tooltipState.visible && tooltipNode && (
        <div
          className="graph-tooltip"
          style={{
            left: Math.min(tooltipState.x + 14, window.innerWidth - 260),
            top: Math.max(tooltipState.y - 10, 4),
          }}
        >
          <div className="graph-tooltip-name">{tooltipNode.label}</div>
          <div className="graph-tooltip-meta">
            <Tag
              style={{
                fontSize: 10,
                lineHeight: '16px',
                padding: '0 4px',
                margin: 0,
              }}
              color="blue"
            >
              {getGranularityLabel(tooltipNode.granularity)}
            </Tag>
            {tooltipNode.category && (
              <span className="graph-tooltip-category">
                {tooltipNode.category}
              </span>
            )}
          </div>
          <div className="graph-tooltip-stars">
            <ImportanceStars value={tooltipNode.importance} />
            <span style={{ marginLeft: 4, fontSize: 10, color: '#999' }}>
              {Math.round(tooltipNode.importance)}/5
            </span>
          </div>
          {tooltipNode.definition && (
            <div className="graph-tooltip-definition">
              {tooltipNode.definition.length > 80
                ? tooltipNode.definition.substring(0, 80) + '...'
                : tooltipNode.definition}
            </div>
          )}
        </div>
      )}

      {/* Info bar */}
      <div className="graph-info">
        <span className="graph-info-badge node-count">
          {currentNodeCount} 节点
        </span>
        <span className="graph-info-sep">|</span>
        <span className="graph-info-badge edge-count">
          {currentEdgeCount} 关系
        </span>
        {(selectedTextbooks.length > 0 ||
          selectedRelationTypes.length > 0 ||
          granularityFilter.length > 0) && (
          <>
            <span className="graph-info-sep">|</span>
            <span className="graph-info-filtered">已筛选</span>
          </>
        )}
        {showIntegrated && (
          <>
            <span className="graph-info-sep">|</span>
            <span className="graph-info-integrated">整合图谱</span>
          </>
        )}
        {viewMode !== 'all' && (
          <>
            <span className="graph-info-sep">|</span>
            <span className="graph-info-viewmode">
              {VIEW_MODE_LABELS[viewMode]}
            </span>
          </>
        )}
      </div>

      {/* Collapsible Legend */}
      {legendItems.length > 0 && (
        <div className="graph-legend">
          <div
            className="graph-legend-header"
            onClick={() => setLegendCollapsed((v) => !v)}
          >
            <span className="graph-legend-title">图例</span>
            <span className="graph-legend-toggle">
              {legendCollapsed ? <RightOutlined /> : <DownOutlined />}
            </span>
          </div>

          {!legendCollapsed && (
            <div className="graph-legend-body">
              {/* Textbook colors */}
              <div className="graph-legend-section">
                <div className="graph-legend-section-title">教材来源</div>
                {legendItems.map((item) => {
                  const isHidden =
                    selectedTextbooks.length > 0 &&
                    !selectedTextbooks.includes(item.id);
                  return (
                    <div
                      key={item.id}
                      className="graph-legend-item"
                      onClick={() => toggleTextbook(item.id)}
                      style={{
                        cursor: 'pointer',
                        opacity: isHidden ? 0.35 : 1,
                      }}
                    >
                      <div
                        className="graph-legend-dot"
                        style={{ background: item.color }}
                      />
                      <span>{item.name}</span>
                      {isHidden && (
                        <EyeInvisibleOutlined
                          style={{ fontSize: 10, color: '#888', marginLeft: 4 }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Node shapes */}
              <div className="graph-legend-section">
                <div className="graph-legend-section-title">节点形状</div>
                <div className="graph-legend-item">
                  <div className="graph-legend-shape-rect" />
                  <span>章节/大类主题</span>
                </div>
                <div className="graph-legend-item">
                  <div className="graph-legend-shape-circle" />
                  <span>核心概念</span>
                </div>
                <div className="graph-legend-item">
                  <div
                    className="graph-legend-dot"
                    style={{
                      background: 'transparent',
                      border: '2px solid #fff',
                      borderStyle: 'double',
                    }}
                  />
                  <span>合并节点</span>
                </div>
                <div className="graph-legend-item">
                  <div
                    className="graph-legend-dot"
                    style={{
                      background: 'transparent',
                      border: '2px dashed #C084FC',
                    }}
                  />
                  <span>教师锁定</span>
                </div>
                <div className="graph-legend-item">
                  <div
                    className="graph-legend-dot"
                    style={{
                      background: 'transparent',
                      border: '2px solid #FFD93D',
                    }}
                  />
                  <span>低质量(&lt;0.65)</span>
                </div>
              </div>

              {/* Edge types */}
              <div className="graph-legend-section">
                <div className="graph-legend-section-title">关系类型</div>
                {edgeTypesPresent.map((rt) => (
                  <div
                    key={rt}
                    className="graph-legend-item"
                    style={{ fontSize: 11 }}
                  >
                    <span
                      className="graph-legend-edge-line"
                      style={{
                        borderBottomColor:
                          EDGE_TYPE_DISPLAY_COLORS[rt] || '#666',
                      }}
                    />
                    <span>{getEdgeTypeLabel(rt)}</span>
                  </div>
                ))}
                {edgeTypesPresent.length === 0 && (
                  <div className="graph-legend-item" style={{ color: '#666' }}>
                    无关系数据
                  </div>
                )}
              </div>

              {/* Interactions hint */}
              <div
                className="graph-legend-section"
                style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 6 }}
              >
                <div
                  className="graph-legend-item"
                  style={{ fontSize: 10, color: '#888' }}
                >
                  <span>悬停查看详情 | 点击折叠展开</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default GraphCanvas;
