# Suggestions for Improving TutorialGuideScreen.kt

This plan refactors the `TutorialGuideScreen` to improve performance, maintainability, and user experience by moving to a `LazyColumn` architecture, hoisting state for a better accordion experience, and isolating data from the UI layer.

## Proposed Changes

### UI & Architecture Improvements

#### [MODIFY] [TutorialGuideScreen.kt](file:///C:/Projects/ap-tracker/android/app/src/main/java/com/jones/aptracker/ui/TutorialGuideScreen.kt)
- **Move Data Out of Composable**: Extract the hardcoded FAQ list to a companion object or a static provider. This prepares the code for localization and keeps the UI logic clean.
- **Switch to `LazyColumn`**: Replace the `Column` + `verticalScroll` with a `LazyColumn`. While the current list is short, `LazyColumn` is more idiomatic for lists in Compose and handles larger datasets efficiently.
- **Hoisted Accordion State**: Modify `FaqAccordionCard` to accept an `isExpanded` boolean and an `onClick` lambda. In `TutorialGuideScreen`, track the `expandedTopicId` so that expanding one topic automatically collapses others, providing a cleaner UI.
- **Component Extraction**: Extract the "Intro Card" into a private `@Composable` function to reduce nesting in the main screen.

### Clean Code & Best Practices
- **Localization**: (Recommended) Move all hardcoded strings to `res/values/strings.xml`.
- **Theme Consistency**: Use `MaterialTheme` colors consistently (already mostly done, but ensuring all hardcoded `copy(alpha = ...)` values are justified).

## Verification Plan

### Automated Tests
- N/A (UI refactor focus).

### Manual Verification
- Deploy to device/emulator.
- Verify that clicking a topic expands it.
- Verify that expanding a new topic collapses the previously expanded one.
- Scroll through the list to ensure `LazyColumn` rendering is smooth.
