'use strict';
// Screen-space measuring guide for the visible lower bench. It never assigns
// champion identities: a ruler measures pixels, not a segmented unit contour.
(function (global) {
  const REFERENCE_WIDTH = 1920;
  const REFERENCE_HEIGHT = 1080;
  const VALID_GEOMETRY = new Set([
    'reference_candidate', 'arena_candidate', 'standard_screen_geometry'
  ]);

  function geometry(spatial) {
    if (!VALID_GEOMETRY.has(spatial?.own_bench_geometry_status)) return null;
    const slots = spatial.own_bench;
    if (!Array.isArray(slots) || slots.length !== 9) return null;
    const centers = [];
    for (let i = 0; i < 9; i++) {
      const row = slots.find(slot => slot.id === `R${i + 1}`);
      const point = row?.center;
      if (!Array.isArray(point) || point.length !== 2 ||
          !point.every(Number.isFinite)) return null;
      const [x, y] = point;
      if (x < 0 || x >= REFERENCE_WIDTH || y < 0 || y >= REFERENCE_HEIGHT) return null;
      centers.push({x, y});
    }
    const gaps = centers.slice(1).map((point, index) => point.x - centers[index].x);
    if (gaps.some(gap => gap < 60 || gap > 200)) return null;
    const sortedGaps = [...gaps].sort((a, b) => a - b);
    const pitch = (sortedGaps[3] + sortedGaps[4]) / 2;
    if (gaps.some(gap => Math.abs(gap - pitch) > pitch * 0.25)) return null;
    const ys = centers.map(point => point.y).sort((a, b) => a - b);
    const benchY = ys[4];
    if (ys.some(y => Math.abs(y - benchY) > 12)) return null;
    const left = centers[0].x - gaps[0] / 2;
    const right = centers[8].x + gaps[7] / 2;
    const rulerY = benchY + 43;
    if (left < 0 || right >= REFERENCE_WIDTH || rulerY >= REFERENCE_HEIGHT) return null;
    return {centers, pitch, left, right, benchY, rulerY};
  }

  function draw(context, canvas, spatial) {
    const guide = geometry(spatial);
    if (!guide) return false;
    const sx = canvas.width / REFERENCE_WIDTH;
    const sy = canvas.height / REFERENCE_HEIGHT;
    const segment = (x1, y1, x2, y2) => {
      context.beginPath();
      context.moveTo(x1 * sx, y1 * sy);
      context.lineTo(x2 * sx, y2 * sy);
      context.stroke();
    };
    context.save();
    context.lineWidth = Math.max(1, canvas.width / 1500);
    context.strokeStyle = 'rgba(105, 228, 174, 0.78)';
    context.fillStyle = 'rgba(105, 228, 174, 0.95)';
    segment(guide.left, guide.rulerY, guide.right, guide.rulerY);
    // Every small tick represents 10 source-image pixels. The image and guide
    // are scaled by the same factors when the capture resolution changes.
    for (let px = 0; guide.left + px <= guide.right; px += 10) {
      const x = guide.left + px;
      const major = px % 50 === 0;
      segment(x, guide.rulerY, x, guide.rulerY + (major ? 9 : 4));
    }
    context.font = `${Math.max(11, canvas.width / 150)}px sans-serif`;
    for (let i = 0; i < guide.centers.length; i++) {
      const x = guide.centers[i].x;
      context.fillText(`R${i + 1}`, (x - 8) * sx, (guide.rulerY + 22) * sy);
    }
    // Diagonal source-pixel rulers beside each slot. Ticks are spaced by
    // Euclidean distance in the unscaled 1920x1080 source coordinate system.
    context.strokeStyle = 'rgba(255, 218, 128, 0.55)';
    context.fillStyle = 'rgba(255, 218, 128, 0.9)';
    for (const point of guide.centers) {
      const x1 = point.x - guide.pitch * 0.40;
      const y1 = guide.benchY + 25;
      const x2 = point.x - guide.pitch * 0.20;
      const y2 = guide.benchY - 100;
      const dx = x2 - x1, dy = y2 - y1;
      const length = Math.hypot(dx, dy);
      const ux = dx / length, uy = dy / length;
      segment(x1, y1, x2, y2);
      for (let distance = 0; distance <= length; distance += 10) {
        const x = x1 + ux * distance, y = y1 + uy * distance;
        const tick = distance % 50 === 0 ? 6 : 3;
        segment(x - uy * tick, y + ux * tick,
                x + uy * tick, y - ux * tick);
      }
    }
    context.restore();
    return true;
  }

  function boardGeometry(spatial) {
    if (!VALID_GEOMETRY.has(spatial?.own_geometry_status)) return null;
    const cells = spatial.own_cells;
    if (!Array.isArray(cells) || cells.length !== 28) return null;
    const rows = [];
    for (const letter of 'ABCD') {
      const row = [];
      for (let column = 1; column <= 7; column++) {
        const point = cells.find(cell => cell.id === `${letter}${column}`)?.center;
        if (!Array.isArray(point) || point.length !== 2 ||
            !point.every(Number.isFinite)) return null;
        if (point[0] < 0 || point[0] >= REFERENCE_WIDTH ||
            point[1] < 0 || point[1] >= REFERENCE_HEIGHT) return null;
        row.push(point);
      }
      if (row.some((point, index) => index && point[0] <= row[index - 1][0])) return null;
      rows.push(row);
    }
    if (rows.some((row, index) => index && row[0][1] <= rows[index - 1][0][1])) return null;
    const left = rows[3][0][0], right = rows[3][6][0];
    const y = rows[3][0][1] + 38;
    if (y >= REFERENCE_HEIGHT || right - left < 400) return null;
    return {left, right, y, diagonalStart: [left - 24, y - 12],
      diagonalEnd: [rows[0][0][0] - 24, rows[0][0][1] - 20]};
  }

  function drawBoard(context, canvas, spatial) {
    const guide = boardGeometry(spatial);
    if (!guide) return false;
    const sx = canvas.width / REFERENCE_WIDTH;
    const sy = canvas.height / REFERENCE_HEIGHT;
    const segment = (x1, y1, x2, y2) => {
      context.beginPath();
      context.moveTo(x1 * sx, y1 * sy);
      context.lineTo(x2 * sx, y2 * sy);
      context.stroke();
    };
    context.save();
    context.lineWidth = Math.max(1, canvas.width / 1500);
    context.strokeStyle = 'rgba(116, 216, 255, 0.72)';
    segment(guide.left, guide.y, guide.right, guide.y);
    for (let distance = 0; guide.left + distance <= guide.right; distance += 10) {
      const x = guide.left + distance;
      segment(x, guide.y, x, guide.y + (distance % 50 === 0 ? 9 : 4));
    }
    const [x1, y1] = guide.diagonalStart;
    const [x2, y2] = guide.diagonalEnd;
    const dx = x2 - x1, dy = y2 - y1;
    const length = Math.hypot(dx, dy);
    const ux = dx / length, uy = dy / length;
    context.strokeStyle = 'rgba(255, 218, 128, 0.58)';
    segment(x1, y1, x2, y2);
    for (let distance = 0; distance <= length; distance += 10) {
      const x = x1 + ux * distance, y = y1 + uy * distance;
      const tick = distance % 50 === 0 ? 6 : 3;
      segment(x - uy * tick, y + ux * tick,
              x + uy * tick, y - ux * tick);
    }
    context.fillStyle = 'rgba(116, 216, 255, 0.95)';
    context.font = `${Math.max(11, canvas.width / 150)}px sans-serif`;
    context.fillText('TABULEIRO · 10 px', (guide.left + 6) * sx, (guide.y + 24) * sy);
    context.restore();
    return true;
  }

  global.BenchRuler = Object.freeze({geometry, draw, boardGeometry, drawBoard});
})(typeof window === 'undefined' ? globalThis : window);
