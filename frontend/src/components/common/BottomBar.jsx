export default function BottomBar({ left, right }) {
  return (
    <div className="bottom-bar">
      <div className="row">{left}</div>
      <div className="row">{right}</div>
    </div>
  );
}
