import {
  Component,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';

interface PickerItem {
  value: string;
  label: string;
}

interface LabelPart {
  text: string;
  hit: boolean;
}

/**
 * Single-select column chooser with type-to-filter.
 *
 * A plain <select> is unusable once a feed carries a hundred columns, so this
 * keeps the same one-value-in/one-value-out contract but lets you search.
 */
@Component({
  selector: 'app-column-picker',
  templateUrl: './column-picker.html',
  styleUrl: './column-picker.scss',
})
export class ColumnPicker {
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly options = input<string[]>([]);
  readonly value = input<string>('');
  readonly placeholder = input<string>('Select a column');
  /** Label for a "no column" choice. Empty string means the choice is absent. */
  readonly emptyLabel = input<string>('');
  readonly disabled = input<boolean>(false);
  readonly valueChange = output<string>();

  readonly open = signal(false);
  readonly query = signal('');
  readonly activeIndex = signal(0);

  private readonly searchBox = viewChild<ElementRef<HTMLInputElement>>('search');

  readonly items = computed<PickerItem[]>(() => {
    const columns = this.options().map((column) => ({ value: column, label: column }));
    const empty = this.emptyLabel();
    return empty ? [{ value: '', label: empty }, ...columns] : columns;
  });

  readonly filtered = computed<PickerItem[]>(() => {
    const needle = this.query().trim().toLowerCase();
    if (!needle) return this.items();
    return this.items().filter((item) => item.label.toLowerCase().includes(needle));
  });

  readonly label = computed(() => {
    const current = this.value();
    return this.items().find((item) => item.value === current)?.label ?? '';
  });

  constructor() {
    // Focus the search box as soon as the panel appears.
    effect(() => {
      if (this.open()) {
        queueMicrotask(() => this.searchBox()?.nativeElement.focus());
      }
    });
  }

  toggle(): void {
    if (this.disabled()) return;
    const next = !this.open();
    this.open.set(next);
    if (next) {
      this.query.set('');
      this.activeIndex.set(Math.max(0, this.filtered().findIndex((i) => i.value === this.value())));
    }
  }

  choose(value: string, event?: Event): void {
    event?.preventDefault();
    this.open.set(false);
    this.query.set('');
    if (value !== this.value()) {
      this.valueChange.emit(value);
    }
  }

  onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
    this.activeIndex.set(0);
  }

  onKey(event: KeyboardEvent): void {
    const options = this.filtered();
    if (event.key === 'Escape') {
      this.open.set(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!options.length) return;
      const step = event.key === 'ArrowDown' ? 1 : -1;
      this.activeIndex.set((this.activeIndex() + step + options.length) % options.length);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const chosen = options[this.activeIndex()];
      if (chosen) this.choose(chosen.value);
    }
  }

  /** Splits a label so the matched run can be highlighted without innerHTML. */
  parts(label: string): LabelPart[] {
    const needle = this.query().trim();
    if (!needle) return [{ text: label, hit: false }];
    const at = label.toLowerCase().indexOf(needle.toLowerCase());
    if (at < 0) return [{ text: label, hit: false }];
    return [
      { text: label.slice(0, at), hit: false },
      { text: label.slice(at, at + needle.length), hit: true },
      { text: label.slice(at + needle.length), hit: false },
    ].filter((part) => part.text.length > 0);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) {
      this.open.set(false);
    }
  }
}
