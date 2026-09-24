import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/layout/Layout";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<div>Overview</div>} />
          <Route path="cpu" element={<div>CPU</div>} />
          <Route path="memory" element={<div>Memory</div>} />
          <Route path="storage" element={<div>Storage</div>} />
          <Route path="network" element={<div>Network</div>} />
          <Route path="processes" element={<div>Processes</div>} />
          <Route path="services" element={<div>Services</div>} />
          <Route path="events" element={<div>Events</div>} />
          <Route path="alerts" element={<div>Alerts</div>} />
          <Route path="server" element={<div>Server</div>} />
          <Route path="settings" element={<div>Settings</div>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;