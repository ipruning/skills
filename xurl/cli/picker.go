package cli

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ─── Styles ─────────────────────────────────────────────────────────

var (
	titleStyle    = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("12"))
	itemStyle     = lipgloss.NewStyle().PaddingLeft(2)
	selectedStyle = lipgloss.NewStyle().PaddingLeft(0).Foreground(lipgloss.Color("10")).Bold(true)
	cursorStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("10"))
	subtleStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("8"))
)

// ─── Picker model ───────────────────────────────────────────────────

type pickerModel struct {
	title    string
	items    []string
	cursor   int
	choice   string
	quitting bool
}

func newPickerModel(title string, items []string) pickerModel {
	return pickerModel{
		title: title,
		items: items,
	}
}

func (m pickerModel) Init() tea.Cmd { return nil }

func (m pickerModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q", "esc":
			m.quitting = true
			return m, tea.Quit
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < len(m.items)-1 {
				m.cursor++
			}
		case "enter":
			m.choice = m.items[m.cursor]
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m pickerModel) View() string {
	if m.quitting && m.choice == "" {
		return subtleStyle.Render("Cancelled.") + "\n"
	}
	if m.choice != "" {
		return ""
	}

	s := titleStyle.Render(m.title) + "\n\n"
	for i, item := range m.items {
		if i == m.cursor {
			s += cursorStyle.Render("▸ ") + selectedStyle.Render(item) + "\n"
		} else {
			s += itemStyle.Render("  "+item) + "\n"
		}
	}
	s += "\n" + subtleStyle.Render("↑/↓ navigate • enter select • q quit") + "\n"
	return s
}

// ─── Public API ─────────────────────────────────────────────────────

// RunPicker launches an interactive Bubble Tea list picker and returns the
// selected item, or an empty string if the user cancelled.
func RunPicker(title string, items []string) (string, error) {
	if len(items) == 0 {
		return "", fmt.Errorf("no items to pick from")
	}

	m := newPickerModel(title, items)
	p := tea.NewProgram(m)

	result, err := p.Run()
	if err != nil {
		return "", err
	}

	final := result.(pickerModel)
	return final.choice, nil
}
