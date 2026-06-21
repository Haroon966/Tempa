import { useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { sectionPath, type NavSection } from "@/components/dashboard/nav"

export function useNavigateSection() {
  const navigate = useNavigate()
  return useCallback((section: NavSection) => navigate(sectionPath(section)), [navigate])
}
