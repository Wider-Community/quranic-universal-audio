const source = `
# May Require Boundary Adjustment

This flags a segment that may start or end slightly off — a word clipped at an edge, or a boundary worth nudging. It often overlaps with low confidence, and on a closer look it can point to other issues too. Many are fine and can be ignored after a quick check.

> By the end this should be zero — adjusted or ignored. It follows similar editing patterns to low confidence.

`;

export default source;
