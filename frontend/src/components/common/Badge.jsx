/**
 * variant: 'danger' | 'accent' | 'success' | 'warning'
 */
export default function Badge({ children, variant = 'accent' }) {
  return <span className={`badge b-${variant}`}>{children}</span>;
}
