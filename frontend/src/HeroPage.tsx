import React, { useEffect, useState } from "react";
import { ChevronDown, Activity } from "lucide-react";

interface HeroPageProps {
  onEnter: () => void;
}

export default function HeroPage({ onEnter }: HeroPageProps) {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    // Fade in after mount
    const t = setTimeout(() => setVisible(true), 80);
    return () => clearTimeout(t);
  }, []);

  function handleEnter() {
    setExiting(true);
    setTimeout(onEnter, 700);
  }

  // Keyboard shortcut — Enter or Space
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleEnter();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className={"hero-shell" + (exiting ? " hero-exit" : "") + (visible ? " hero-visible" : "")}
      aria-label="OceanEmbed-NIO landing screen"
    >
      {/* Background image — the reference ocean render */}
      <div className="hero-bg" aria-hidden="true">
        <img
          src="/hero-ocean.png"
          alt=""
          className="hero-bg-img"
          draggable={false}
        />
        {/* Gradient overlay — darkens bottom so text pops cleanly */}
        <div className="hero-overlay" />
      </div>

      {/* Institutional masthead strip — same as main app */}
      <div className="hero-masthead">
        <span>SIH 2026 · Team DeepSindhu</span>
        <span>Problem context: Ministry of Earth Sciences (MoES) · INCOIS</span>
      </div>

      {/* Centre content */}
      <div className="hero-content">
        {/* Logo / wordmark */}
        <div className="hero-brand">
          <img className="hero-logo-mark" src="/oceanembed-mark.png" alt="OceanEmbed logo" />
          <span className="hero-wordmark"><span>Ocean</span><b>Embed</b></span>
          <span className="hero-submark">NIO · North Indian Ocean</span>
        </div>

        {/* Primary headline */}
        <h1 className="hero-headline">
          Reading the ocean,<br />
          one thermal layer at a time.
        </h1>

        {/* Sub-copy — tied directly to the problem statement context */}
        <p className="hero-subline">
          A research decision-support prototype for reconstructing upper-ocean thermal
          structure across the Bay of Bengal and Arabian Sea.
          Built for Smart India Hackathon 2026 · Problem SIH26066.
        </p>

        {/* Stat pills */}
        <div className="hero-pills" aria-label="Key capabilities">
          <span><Activity size={14} aria-hidden="true" />15 depth levels · 0–1000 m</span>
          <span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M12 22V12M12 12C12 12 6 9 6 5a6 6 0 0 1 12 0c0 4-6 7-6 7z"/>
            </svg>
            D26 · TCHP · MLD-T diagnostics
          </span>
          <span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/>
            </svg>
            3-state reliability gate
          </span>
          <span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            CF-1.10 NetCDF exports
          </span>
        </div>

        {/* Enter CTA */}
        <button
          className="hero-cta"
          onClick={handleEnter}
          aria-label="Enter the OceanEmbed workspace"
        >
          Enter the workspace
          <ChevronDown size={19} aria-hidden="true" />
        </button>

        {/* Research disclaimer — mirrors footer text */}
        <p className="hero-disclaimer">
          Research prototype · Not an operational cyclone intensity warning system ·
          Synthetic engineering fixture active
        </p>
      </div>

      {/* Scroll cue at bottom */}
      <div className="hero-scroll-cue" aria-hidden="true">
        <ChevronDown size={22} className="hero-bounce" />
      </div>
    </div>
  );
}
