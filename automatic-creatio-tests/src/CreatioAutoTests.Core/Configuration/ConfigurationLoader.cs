using System.Text.Json;

namespace CreatioAutoTests.Configuration;

/// <summary>
/// Reads the framework's JSON configuration. Everything goes through System.Text.Json with the
/// same lenient reader settings, so comments and trailing commas are allowed in every file.
/// </summary>
public sealed class ConfigurationLoader
{
    /// <summary>Shared permissive JSON reader settings for comments, trailing commas, and case-insensitive keys.</summary>
    public static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private readonly string _rootDirectory;

    /// <summary>Initializes configuration loading relative to a required root directory.</summary>
    public ConfigurationLoader(string rootDirectory)
    {
        if (string.IsNullOrWhiteSpace(rootDirectory))
        {
            throw new ArgumentException("Configuration root directory must be provided.", nameof(rootDirectory));
        }

        _rootDirectory = rootDirectory;
    }

    /// <summary>Combines a configuration-relative path with the configured root directory.</summary>
    public string Resolve(string relativePath) => Path.Combine(_rootDirectory, relativePath);

    /// <summary>Reads a required file and fails with the path when it is missing or malformed.</summary>
    public T Load<T>(string relativePath) where T : new()
    {
        var path = Resolve(relativePath);

        if (!File.Exists(path))
        {
            throw new FileNotFoundException("Configuration file was not found: " + path, path);
        }

        var json = File.ReadAllText(path);

        try
        {
            return JsonSerializer.Deserialize<T>(json, SerializerOptions)
                   ?? throw new InvalidOperationException("Configuration file '" + path + "' deserialized to null.");
        }
        catch (JsonException ex)
        {
            throw new InvalidOperationException(
                "Configuration file '" + path + "' is not valid JSON for " + typeof(T).Name + ": " + ex.Message, ex);
        }
    }

    /// <summary>Reads an optional file, returning defaults when it is absent.</summary>
    public T LoadOrDefault<T>(string relativePath) where T : new()
    {
        return File.Exists(Resolve(relativePath)) ? Load<T>(relativePath) : new T();
    }


    /// <summary>
    /// Reads every page file from a directory, one page per file. The file name is only a label;
    /// the page's identity is the "name" inside it.
    /// </summary>
    /// <param name="relativeDirectory">The folder, relative to the root or absolute.</param>
    /// <param name="optional">An extra pages folder (<c>PagesFolders</c>): missing or empty gives no pages, and each page
    /// keeps its full path as its source file, so a name declared twice names both files.</param>
    public IReadOnlyList<PageDefinition> LoadPages(string relativeDirectory, bool optional = false)
    {
        var directory = Resolve(relativeDirectory);

        if (!Directory.Exists(directory))
        {
            if (optional)
            {
                return Array.Empty<PageDefinition>();
            }

            throw new DirectoryNotFoundException(
                "Pages directory was not found: " + directory +
                ". Each page lives in its own .json file there.");
        }

        var files = Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        if (files.Length == 0 && !optional)
        {
            throw new InvalidOperationException("No page files were found in " + directory + ".");
        }

        var pages = new List<PageDefinition>(files.Length);

        foreach (var file in files)
        {
            PageDefinition page;
            try
            {
                page = JsonSerializer.Deserialize<PageDefinition>(File.ReadAllText(file), SerializerOptions)
                       ?? throw new InvalidOperationException("Page file '" + file + "' deserialized to null.");
            }
            catch (JsonException ex)
            {
                throw new InvalidOperationException(
                    "Page file '" + file + "' is not valid JSON: " + ex.Message, ex);
            }

            page.SourceFile = optional ? Path.GetFullPath(file) : Path.GetFileName(file);

            // The page owns its elements, so each one learns which page it belongs to here.
            foreach (var element in page.Elements)
            {
                element.Page = page.Name;
            }

            pages.Add(page);
        }

        return pages;
    }

    /// <summary>
    /// Reads every process file from a directory, one process per file. The directory is optional:
    /// a project without process cases has none.
    /// </summary>
    public IReadOnlyList<ProcessDefinition> LoadProcesses(string relativeDirectory)
    {
        var directory = Resolve(relativeDirectory);
        if (!Directory.Exists(directory))
        {
            return Array.Empty<ProcessDefinition>();
        }

        var processes = new List<ProcessDefinition>();
        foreach (var file in Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories).OrderBy(f => f, StringComparer.OrdinalIgnoreCase))
        {
            ProcessDefinition process;
            try
            {
                process = JsonSerializer.Deserialize<ProcessDefinition>(File.ReadAllText(file), SerializerOptions)
                          ?? throw new InvalidOperationException("Process file '" + file + "' deserialized to null.");
            }
            catch (JsonException ex)
            {
                throw new InvalidOperationException("Process file '" + file + "' is not valid JSON: " + ex.Message, ex);
            }

            if (string.IsNullOrWhiteSpace(process.Name))
            {
                throw new InvalidOperationException("Process file '" + file + "' has no name.");
            }

            process.SourceFile = Path.GetFullPath(file);
            processes.Add(process);
        }

        return processes;
    }

    /// <summary>Reads static.values.json, flattening every JSON scalar into a string.</summary>
    public IReadOnlyDictionary<string, string> LoadStaticValues(string relativePath)
    {
        var path = Resolve(relativePath);
        var result = new Dictionary<string, string>(StringComparer.Ordinal);

        if (!File.Exists(path))
        {
            return result;
        }

        using var document = JsonDocument.Parse(
            File.ReadAllText(path),
            new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true });

        foreach (var property in document.RootElement.EnumerateObject())
        {
            result[property.Name] = property.Value.ValueKind switch
            {
                JsonValueKind.String => property.Value.GetString() ?? string.Empty,
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                JsonValueKind.Null => string.Empty,
                _ => property.Value.GetRawText()
            };
        }

        return result;
    }
}
