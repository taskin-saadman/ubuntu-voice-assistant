import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { VoiceClient } from "./client";
import "./styles.css";

const client = new VoiceClient();
createRoot(document.getElementById("root")!).render(<StrictMode><App client={client} /></StrictMode>);
