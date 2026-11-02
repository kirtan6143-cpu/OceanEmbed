import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import HeroPage from "./HeroPage";
import "./styles.css";
import "./workspace-background.css";

function Root() {
  const [showApp, setShowApp] = useState(false);
  return showApp ? <App /> : <HeroPage onEnter={() => setShowApp(true)} />;
}

createRoot(document.getElementById("root")!).render(<Root />);
