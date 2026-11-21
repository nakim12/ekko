import type { Metadata } from "next";
import { Suspense } from "react";
import ReportApp from "./ReportApp";
import styles from "./report.module.css";

export const metadata: Metadata = {
  title: "Ekko: your tilt report",
  description: "Enter your Riot ID to see how your last game ripples into your next one.",
};

export default function ReportPage() {
  return (
    <>
      <nav className={styles.nav}>
        <a className={styles.wordmark} href="/">ekko</a>
        <div className={styles.navLinks}>
          <a href="/#questions">the study</a>
          <a href="https://github.com/nakim12/ekko">github</a>
        </div>
      </nav>
      <main className={styles.main}>
        <Suspense fallback={<div className={styles.lookup} />}>
          <ReportApp />
        </Suspense>
      </main>
      <footer className={styles.footer}>
        <p>
          Ekko isn&apos;t endorsed by Riot Games and doesn&apos;t reflect the views or opinions of Riot Games or
          anyone officially involved in producing or managing Riot Games properties. Riot Games, and all
          associated properties are trademarks or registered trademarks of Riot Games, Inc.
        </p>
      </footer>
    </>
  );
}
