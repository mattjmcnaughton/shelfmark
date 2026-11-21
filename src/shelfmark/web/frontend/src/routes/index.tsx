import { createFileRoute } from "@tanstack/react-router";
import { ReadingDesk } from "../components/ReadingDesk";
import "../desk.css";

export const Route = createFileRoute("/")({
  component: ReadingDesk,
});
