// Two short declarative lines; the second is muted.
export default function EditorialLine({ first, second }) {
  return (
    <p className="editorial">
      <span>{first}</span>
      <span className="editorial-muted">{second}</span>
    </p>
  );
}
