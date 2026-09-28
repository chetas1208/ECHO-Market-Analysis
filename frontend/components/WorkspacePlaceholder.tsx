import { PageHeader } from "./PageHeader";
import styles from "./WorkspacePlaceholder.module.css";

export function WorkspacePlaceholder({ title, eyebrow, description }: { title: string; eyebrow: string; description: string }) {
  return <div className={styles.page}>
    <PageHeader title={title} meta={`${eyebrow} · workspace`} />
    <section className="workspace-placeholder" aria-labelledby="workspace-placeholder-title">
      <div className="workspace-placeholder__mark" aria-hidden="true">◌</div>
      <h2 id="workspace-placeholder-title">{title} is ready for live data</h2>
      <p>{description}</p>
      <span className="quiet-badge">PHASE 2 WORKSPACE</span>
    </section>
  </div>;
}
