/** Reflow PDF line wraps for reading; the source string stays available unchanged. */
export function reflowSource(value: string): string {
  return value.split(/\n\s*\n/).map((paragraph) => paragraph.split('\n').map((line) => line.trim()).reduce((text, line) => {
    if (!text) return line;
    return `${text}${/[A-Za-z0-9]$/.test(text) && /^[A-Za-z0-9]/.test(line) ? ' ' : ''}${line}`;
  }, '')).join('\n\n');
}
