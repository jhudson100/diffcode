#!/usr/bin/env python3

# Copyright (c) 2024 J Hudson
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


#Uses Reportlab (https://www.reportlab.com/opensource/)

import reportlab.pdfgen.canvas
import reportlab.pdfbase
import reportlab.pdfbase.ttfonts
import reportlab.pdfbase.pdfmetrics
import subprocess
import os
import pprint
import collections
import enum
import datetime
import math
import re
import sys
import fnmatch
import argparse

ChangeType = enum.Enum("ChangeType",
    "NEW_CHUNK INSERTED DELETED CONTEXT ADDED_FILE REMOVED_FILE DIFFERING_BINARY"
)

#type is a ChangeType enum
# line1 and line2 give line numbers in the source documents
# content gives the text content (or is None for @)
ChangeInfo = collections.namedtuple( "ChangeInfo",
    "type line1 line2 content"
)

def error(msg):
    sys.stderr.write(msg)
    sys.stderr.write("\n")
    sys.exit(1)

DIMENSIONS={
    "in": 72, "cm": 72/2.54, "mm": 720/2.54, "pt": 1
}
DIMENSION_STRING=" or ".join(DIMENSIONS.keys())
def toPoints(s):
    sfx = s[-2:]
    if sfx not in DIMENSIONS:
        error(f"Bad suffix on dimension '{s}': Should be one of {DIMENSIONS}")
    pfx = s[:-2]
    return float(pfx) * DIMENSIONS[sfx]

def toColor(s):
    tmp = s.split(",")
    if len(tmp) != 3:
        error(f"Bad color specification '{s}': Should be three numbers (each one from 0 to 1) separated by commas")
    try:
        c = [float(q) for q in tmp]
    except ValueError:
        error(f"Bad color specification '{s}': Should be three numbers in the range 0 to 1 separated by commas")
    mn = min(c)
    mx = max(c)
    if mn < 0 or mx > 1:
        error(f"Bad color specification '{s}': Should be three numbers from 0 to 1 separated by commas")
    return tuple(c)

def parseDashPattern(p):
    try:
        tmp = p.split(",")
        tmp = [float(q) for q in tmp]
        if len(tmp) == 1 and tmp[0] == -1:
            return []       #no dashes
        mn = min(tmp)
        if mn < 0:
            raise ValueError()
        return tmp
    except ValueError:
        error("Dash pattern should be a sequence of numbers separated by commas or else a single value of -1 to indicate no dashes")


#approximation of a function call. Need to check later
#to verify group 1 is not keyword: if, while, etc.
funcrex = re.compile(r"\s*([A-Za-z_]\w*\s+)*([A-Za-z_]\w*)\s*\([^)]*\)\s*\{")
classrex = re.compile(r"\s*(public\s+)?class\s+(\w+)\s*[:{]")
def getContainingFunction(filename, lineNumber):
    with open(filename,errors="ignore") as fp:
        data = fp.read()
    idx=0
    lineNum=1
    klass=""
    func=""

    def checkClass():
        nonlocal klass
        M = classrex.match(data,idx)
        if M:
            klass = "class "+M.group(2)

    def checkFunc():
        nonlocal func
        M = funcrex.match(data,idx)
        if M:
            word = M.group(2)
            if word not in ["if","while","for","foreach","switch"]:
                func = "function "+word

    if idx == len(data) or lineNum >= lineNumber:
        checkClass()
        checkFunc()

    while idx < len(data) and lineNum < lineNumber:

        checkClass()
        checkFunc()

        i = data.find("\n", idx )
        if i == -1:
            return "[not in a function]"
        idx = i+1
        lineNum+=1

    if klass and func:
        return f"{klass} , {func}"
    elif klass:
        return klass
    elif func:
        return func
    else:
        return None

fontCounter=1
def registerFont(filename):
    global fontCounter
    if "." in filename:
        fontname = f"MyFont{fontCounter}"
        fontCounter+=1
        reportlab.pdfbase.pdfmetrics.registerFont(
            reportlab.pdfbase.ttfonts.TTFont( fontname, filename )
        )
    else:
        #builtin font
        fontname = filename
    return fontname

def main():

    MACROS = "{pagenum} {numpages} {today} {path1} {path2} {paths}"
    COLOR_HELP = "Specify three numbers 0...1 separated by commas (example: '0,0,0')."
    DIMENSION_HELP = f"Use suffix of {DIMENSION_STRING}."
    FONT_HELP = ("May be the name of a builtin font or else the location of a .ttf file. Builtin fonts: "
                 "Times-{Roman,Bold,Italic,BoldItalic}, Courier[-Bold,-Oblique,-BoldOblique], "
                 "Helvetica[-Bold,-Oblique,-BoldOblique]")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--help",action="help")
    parser.add_argument("-o", default="out.pdf", help="Output filename")
    parser.add_argument("--font", default="Courier", help=f"Font for document. {FONT_HELP}")
    parser.add_argument("path1", help="First path to scan")
    parser.add_argument("path2", help="Second path to scan")
    parser.add_argument("--header-left", default="{paths}", help=f"Header left side. Macros: {MACROS}" )
    parser.add_argument("--header-right", default="Page {pagenum} of {numpages}", help=f"Header right side. Macros: {MACROS}" )
    parser.add_argument("--footer-left", default="{today}", help=f"Footer left side. Macros: {MACROS}" )
    parser.add_argument("--footer-right", default="", help=f"Footer right side. Macros: {MACROS}" )
    parser.add_argument("--font-size", default=10, help="Font size, in points")
    parser.add_argument("--ignore", action="append", help="Glob pattern for files to ignore. May be repeated.")
    parser.add_argument("-w",default="8.5in",help=f"Page width. {DIMENSION_HELP}")
    parser.add_argument("-h",default="11in",help=f"Page height. Use suffix of {DIMENSION_STRING}")
    parser.add_argument("--content-margin-top",default="0.75in",help=f"Distance from page top to content. {DIMENSION_HELP}")
    parser.add_argument("--content-margin-bottom",default="0.75in",help=f"Distance from page bottom to content. {DIMENSION_HELP}")
    parser.add_argument("--header-margin", default="0.5in", help=f"Distance from top of page to header. {DIMENSION_HELP}")
    parser.add_argument("--footer-margin", default="0.5in", help=f"Distance from bottom of page to footer. {DIMENSION_HELP}")
    parser.add_argument("--left-margin", default="0.5in", help=f"Left margin. {DIMENSION_HELP}")
    parser.add_argument("--right-margin", default="0.5in", help=f"Right margin. {DIMENSION_HELP}")
    parser.add_argument("--color-insert-line-number", default="0.5,0.5,0.5", help=f"Color for line numbers of inserted lines. {COLOR_HELP}")
    parser.add_argument("--color-delete-line-number", default="0.5,0.5,0.5", help=f"Color for line numbers of deleted lines. {COLOR_HELP}")
    parser.add_argument("--color-context-line-number", default="0.5,0.5,0.5", help=f"Color for line numbers of context lines. {COLOR_HELP}")
    parser.add_argument("--color-insert-text", default="0,0,0", help=f"Color for text of inserted lines. {COLOR_HELP}")
    parser.add_argument("--color-delete-text", default="0,0,0", help=f"Color for text of deleted lines. {COLOR_HELP}")
    parser.add_argument("--color-context-text", default="0.5,0.5,0.5", help=f"Color for text of context lines. {COLOR_HELP}")
    parser.add_argument("--color-margin-line", default="0,0,0", help=f"Color for margin line. {DIMENSION_HELP}")
    parser.add_argument("--color-chunk-separator", default="0.5,0.5,0.5", help=f"Color for chunk separator. {COLOR_HELP}")
    parser.add_argument("--color-filename", default="0,0,0", help=f"Color for chunk filenames. {COLOR_HELP}")
    parser.add_argument("--color-filename-lines", default="0,0,0", help=f"Color for filename separator lines. {COLOR_HELP}")
    parser.add_argument("--ignore-blank-lines", default="yes", choices=["yes","no"], help="Ignore blank lines in input files: yes or no.")
    parser.add_argument("--date-format",default="%Y-%b-%d",help="Date format. %%b=month, %%d=day, %%Y=year; %%H=hour, %%M=minute, %%S=second; other strftime escapes are supported")
    parser.add_argument("--color-insert-background", default="0.9,0.9,0.9", help=f"Background color for inserted text. {COLOR_HELP}")
    parser.add_argument("--color-delete-background", default="1,1,1", help=f"Background color for deleted text. {COLOR_HELP}")
    parser.add_argument("--color-context-background", default="1,1,1", help=f"Background color for context text. {COLOR_HELP}")
    parser.add_argument("--strikeout-width", default="0.5pt", help=f"Width of strikeout line. Use 0pt to omit. {DIMENSION_HELP}")
    parser.add_argument("--underline-width", default="0.5pt", help=f"Width of underlines. Use 0pt to omit. {DIMENSION_HELP}")
    parser.add_argument("--underline-pattern", default="1,2", help=f"Dash pattern: Should be a series of numbers separated by commas. Numbers specify length in points. For solid underlines, specify a single value of -1")
    parser.add_argument("--header-line-width", default="0.5pt", help=f"Thickness of header/footer line. Use 0pt to omit. {DIMENSION_HELP}.")
    parser.add_argument("--show-containing-function", default="yes", choices=["yes","no"],help=f"Show containing function for each chunk (yes or no)")
    parser.add_argument("--containing-function-font", default="Courier-Oblique", help=f"Font for containing function. {FONT_HELP}")
    parser.add_argument("--containing-function-color", default="0.5,0.5,0.5", help=f"Color for containing function. {COLOR_HELP}")
    parser.add_argument("--discard", action="append", help="Ignore specific change sets within a file. Argument is of form 'filename,lineNumber,linenumber,...'. May be repeated")

    #insert-text 0,0.5,0
    #delete-text 0,5,0,0
    #context-text: 0.5,0.5,0.5
    #insert-background: 0.8,1,0.8
    #delete-background: 1,0.8,0.8
    #context-background: 0.8,0.8,1.0
    #insert-line: 0.3,0.8,0.3
    #delete-line: 1.0,0.5,0.5
    #context-line: 0.5,0.5,1.0

    args = parser.parse_args()

    pageHeight = toPoints(args.h)
    pageWidth = toPoints(args.w)
    outputFile = args.o

    if not args.ignore:
        ignoreGlobs = [
            "*.assets.json", "*.nuget.*", "*.cache", "*.csproj.*", "*.editorconfig",
            "*.exe", "*.dll", "*.so", "*.o", "*.pdb"
        ]
    else:
        ignoreGlobs = args.ignore[:]

    #key=filename; value=list of ints: Discard any change set that
    #includes any of those lines
    changesToIgnoreByFilename={}
    if args.discard:
        for tmp in args.discard:
            X = tmp.split(",")
            ff=X[0]
            for linenum in X[1:]:
                linenum = int(linenum)
                if ff not in changesToIgnoreByFilename:
                    changesToIgnoreByFilename[ff]=[]
                changesToIgnoreByFilename[ff].append(linenum)


    normalFontFile = args.font
    # ~ boldFontFile = None
    # ~ italicFontFile = None
    # ~ boldItalicFontFile = None

    headerLeft = args.header_left
    headerRight = args.header_right
    footerLeft = args.footer_left
    footerRight = args.footer_right

    fontSize = float(args.font_size)

    headerMargin = toPoints(args.header_margin)
    contentMarginTop = toPoints(args.content_margin_top)
    contentMarginBottom = toPoints(args.content_margin_bottom)
    footerMargin = toPoints(args.content_margin_bottom)
    leftMargin = toPoints(args.left_margin)
    rightMargin = toPoints(args.right_margin)

    colorInsertLineNumber = toColor(args.color_insert_line_number)
    colorDeleteLineNumber = toColor(args.color_delete_line_number)
    colorContextLineNumber = toColor(args.color_context_line_number)
    colorContextText = toColor(args.color_context_text)
    colorInsertedText = toColor(args.color_insert_text)
    colorDeletedText = toColor(args.color_delete_text)
    colorContextBackground = toColor(args.color_context_background)
    colorInsertedBackground = toColor(args.color_insert_background)
    colorDeletedBackground = toColor(args.color_delete_background)
    #textColor = (0,0,0)
    headerLineColor = toColor(args.color_margin_line)
    chunkSeparatorColor = toColor(args.color_chunk_separator)
    filenameColor = toColor(args.color_filename)
    filenameLinesColor = toColor(args.color_filename_lines)
    ignoreBlankLines=args.ignore_blank_lines
    strikeoutWidth = toPoints(args.strikeout_width)
    underlineWidth = toPoints(args.underline_width)
    headerLineWidth = toPoints(args.header_line_width)
    underlinePattern = parseDashPattern(args.underline_pattern)
    showContainingFunction = (args.show_containing_function=="yes")
    containingFunctionFontFile = args.containing_function_font
    containingFunctionColor = toColor(args.containing_function_color)

    dir1 = args.path1
    dir2 = args.path2

    tmp=[]
    p1 = os.path.abspath(dir1).split(os.path.sep)
    p2 = os.path.abspath(dir2).split(os.path.sep)
    while len(p1) and len(p2) and p1[0] == p2[0]:
        p1.pop(0)
        p2.pop(0)
    while len(p1) and len(p2) and p1[-1] == p2[-1]:
        p1.pop()
        p2.pop()
    if len(p2) == 0:
        pathdelta = os.path.basename(dir1) + "→" + os.path.basename(dir2)
    else:
        pathdelta = os.path.sep.join(p1) + " > " +os.path.sep.join(p2)       #"→"

    normalFontName = registerFont(normalFontFile)
    containingFunctionFontName = registerFont( containingFunctionFontFile )

    # ~ if boldFontFile != None:
        # ~ reportlab.pdfbase.pdfmetrics.registerFont(
            # ~ reportlab.pdfbase.ttfonts.TTFont( "MyFontBold", boldFontFile )
        # ~ )
        # ~ boldFontName = "MyFontBold"
    # ~ else:
        # ~ boldFontName = "Courier-Bold"

    # ~ if italicFontFile != None:
        # ~ reportlab.pdfbase.pdfmetrics.registerFont(
            # ~ reportlab.pdfbase.ttfonts.TTFont( "MyFontItalic", italicFontFile )
        # ~ )
        # ~ italicFontName = "MyFontItalic"
    # ~ else:
        # ~ italicFontName = "Courier-Oblique"

    # ~ if boldItalicFontFile != None:
        # ~ reportlab.pdfbase.pdfmetrics.registerFont(
            # ~ reportlab.pdfbase.ttfonts.TTFont( "MyFontBoldItalic", boldItalicFontFile )
        # ~ )
        # ~ boldItalicFontName = "MyFontBoldItalic"
    # ~ else:
        # ~ boldItalicFontName = "Courier-BoldOblique"


    tmp = datetime.datetime.now()
    today = tmp.strftime(args.date_format)

    ascent, descent = reportlab.pdfbase.pdfmetrics.getAscentDescent( normalFontName, fontSize)

    numPages=0

    pageIsOpen=False
    pageNum=1
    numLineNumberDigits=1       #FIXME


    def getHeaderAndFooter():
        tmp=[]
        for s in [headerLeft, headerRight, footerLeft, footerRight]:
            s = s.replace("{pagenum}", str(pageNum) )
            s = s.replace("{numpages}", str(numPages-1) )
            s = s.replace("{today}", today )
            s = s.replace("{path1}", dir1 )
            s = s.replace("{path2}", dir2 )
            s = s.replace("{paths}", pathdelta )
            tmp.append(s)
        return tmp

    def preparePage():
        nonlocal pageIsOpen,Y,pageNum,numPages
        if pageIsOpen:
            return

        hl, hr, fl, fr = getHeaderAndFooter()

        cvs.setFillColorRGB(0,0,0)
        cvs.setStrokeColorRGB(0,0,0)
        cvs.setFont(normalFontName,fontSize)

        cvs.drawString(leftMargin, pageHeight-headerMargin, hl )
        cvs.drawRightString(pageWidth-rightMargin, pageHeight-headerMargin,hr)
        cvs.drawString(leftMargin, footerMargin-fontSize, fl )
        cvs.drawRightString(pageWidth-rightMargin, footerMargin-fontSize, fr )

        pageNum+=1
        if numPages < pageNum:
            numPages = pageNum

        cvs.setStrokeColorRGB(*headerLineColor)

        cvs.setLineWidth(headerLineWidth)
        cvs.line( leftMargin, pageHeight-contentMarginBottom,
                  pageWidth-rightMargin, pageHeight-contentMarginBottom
        )
        cvs.line( leftMargin, contentMarginTop,
                  pageWidth-rightMargin, contentMarginTop
        )
        # ~ cvs.setStrokeColorRGB(0,0,0)
        pageIsOpen=True
        Y = pageHeight - contentMarginBottom - fontSize

    def endPage():
        nonlocal pageIsOpen
        if not pageIsOpen:
            return
        cvs.showPage()
        pageIsOpen=False

    def checkIfPageIsFull():
        nonlocal Y
        if pageIsOpen and Y < contentMarginBottom:
            endPage()

    def drawLine(x1,y1,x2,y2,weight,color, **kw):
        checkIfPageIsFull()
        preparePage()
        cvs.setStrokeColorRGB(*color)
        cvs.setLineWidth(weight)
        cvs.setDash(kw.get("dash",[]))
        cvs.line(x1,y1,x2,y2)

    def outputLineNumber(cvs,Y,lineNumber,isFirstLine,changeType):
        t = cvs.beginText(leftMargin,Y)
        match(changeType):
            case ChangeType.INSERTED:
                color = colorInsertLineNumber
            case ChangeType.DELETED:
                color = colorDeleteLineNumber
            case ChangeType.CONTEXT:
                color = colorContextLineNumber
            case _:
                assert 0,f"{changeType}"

        t.setFillColorRGB(*color)
        t.setStrokeColorRGB(*color)
        t.setFont(normalFontName,fontSize)
        if lineNumber == None:
            t.textOut( " "*(numLineNumberDigits+1) )
        elif isFirstLine:
            formatString = "{:"+str(numLineNumberDigits)+"d} "
            t.textOut( formatString.format(lineNumber) )
        else:
            if numLineNumberDigits > 3:
                numdots = 3
            else:
                numdots = numLineNumberDigits
            t.textOut( ("."*numdots) + " " )
        #t.setFillColorRGB(*textColor)
        #t.setStrokeColorRGB(*textColor)
        x = t.getX()
        cvs.drawText(t)
        return x

    def drawStrikeoutsAndUnderlines(strikes,underlines):
        currcolor = None
        currw = None
        currdash=None
        for x1,x2,y,width,color,dashPattern in strikes+underlines:
            if currcolor != color:
                cvs.setStrokeColorRGB( *color )
                currcolor = color
            if currw != width:
                cvs.setLineWidth( width )
                currw = width
            dashPattern = tuple(dashPattern)
            if currdash != dashPattern:
                cvs.setDash(dashPattern)
                currdash = dashPattern
            dp = tuple(dashPattern)
            cvs.line( x1,y,x2,y )
        cvs.setDash([])

    def drawRect(x,y,w,h,color):
        cvs.setFillColorRGB(*color)
        cvs.rect(x,y,w,h,stroke=0,fill=1)

    def charWidth(c):
        return reportlab.pdfbase.pdfmetrics.stringWidth(
            c, normalFontName, fontSize
        )

    def outputText(txt, lineNumber, changeType):
        nonlocal Y

        checkIfPageIsFull()
        preparePage()

        x = outputLineNumber(cvs,Y,lineNumber,True,changeType)

        t = cvs.beginText(x,Y)
        t.setFont( normalFontName, fontSize )

        match(changeType):
            case ChangeType.INSERTED:
                fg = colorInsertedText
                bg = colorInsertedBackground
            case ChangeType.DELETED:
                fg = colorDeletedText
                bg = colorDeletedBackground
            case ChangeType.CONTEXT:
                fg = colorContextText
                bg = colorContextBackground
            case _:
                assert 0,f"{changeType}"
        t.setFillColorRGB( *fg )

        strikes = []
        underlines = []
        startDrawingLines=False

        for c in txt:
            doLineNumber=False
            if t.getX() + charWidth(c)  >= pageWidth - rightMargin:
                if changeType == ChangeType.DELETED:
                    #truncate; draw arrow
                    x1 = t.getX()+0.1*charWidth(c)
                    x2 = t.getX()+charWidth(c)
                    y1 = Y+0.5*fontSize
                    y2 = y1 + 0.3*fontSize
                    y3 = y1 - 0.3*fontSize
                    cvs.setFillColorRGB( *colorDeletedText )
                    p = cvs.beginPath()
                    p.moveTo(x1,y2)
                    p.lineTo(x1,y3)
                    p.lineTo(x2,y1)
                    p.lineTo(x1,y2)
                    cvs.drawPath( p, stroke=0, fill=1)
                    break
                else:
                    #go to next line down
                    t.moveCursor(0,fontSize)
                    Y -= fontSize
                    doLineNumber=True

            if Y < contentMarginBottom:
                #we've filled the current page, so finish this text
                #object and start a new page
                cvs.drawText(t)
                drawStrikeoutsAndUnderlines(strikes,underlines)
                strikes=[]
                underlines=[]
                endPage()
                preparePage()
                t = cvs.beginText(leftMargin,Y)
                doLineNumber=True
            if doLineNumber:
                outputLineNumber(cvs,Y,lineNumber,False,changeType)


            if not c.isspace():
                startDrawingLines=True

            if bg != None and startDrawingLines:
                w = charWidth(c)
                drawRect(t.getX(),Y+descent,w,fontSize*0.95, bg )

            x1 = t.getX()
            t.textOut(c)
            x2 = t.getX()


            if changeType == ChangeType.DELETED and startDrawingLines and strikeoutWidth > 0:
                strikes.append( (x1,x2,Y + fontSize * 0.4, strikeoutWidth, colorDeletedText, []) )

            if changeType == ChangeType.INSERTED and startDrawingLines and underlineWidth > 0:
                underlines.append( (x1,x2,Y-0.07*fontSize, underlineWidth, colorInsertedText, underlinePattern ) )


        cvs.drawText(t)
        drawStrikeoutsAndUnderlines(strikes,underlines)

        strikes=[]
        underlines=[]

        #note: This function leaves Y at the last
        #line of text, so the caller must decrement Y
        #if more text is to be written
    #end function


    def drawChunkSeparator(Y):
        cvs.setStrokeColorRGB(*chunkSeparatorColor)
        drawLine( leftMargin, Y, pageWidth-rightMargin, Y, 0.5, chunkSeparatorColor, dash=[5,4] )



    changeset = getDifferences(dir1,dir2)

    #do twice: Once to get page count, once to render it
    for i in range(2):
        pageNum=1
        print("*"*20)
        cvs = reportlab.pdfgen.canvas.Canvas(
            filename=outputFile,
            pagesize=(pageWidth,pageHeight)
        )

        preparePage()
        i=0
        for fname in sorted(changeset.keys()):
            basename = os.path.basename(fname)
            ignore=False
            for p in ignoreGlobs:
                if fnmatch.fnmatch(basename,p) :
                    ignore=True
                    break

            if ignore:
                continue

            SPACE=2
            if Y < contentMarginBottom + SPACE+fontSize+SPACE+SPACE+fontSize:
                endPage()


            txt = os.path.basename(fname)

            if len(changeset[fname]) >= 1 and changeset[fname][0].type == ChangeType.REMOVED_FILE:
                txt += " [file deleted]"
            if len(changeset[fname]) >= 1 and changeset[fname][0].type == ChangeType.ADDED_FILE:
                txt += " [file added]"
            if len(changeset[fname]) >= 1 and changeset[fname][0].type == ChangeType.DIFFERING_BINARY:
                txt += " [binary files differ]"
            preparePage()
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameLinesColor)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameLinesColor)
            Y-=fontSize
            cvs.setFillColorRGB(*filenameColor)
            cvs.setStrokeColorRGB(*filenameColor)
            cvs.setFont( normalFontName, fontSize )
            cvs.drawCentredString(pageWidth/2,Y,txt)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameLinesColor)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameLinesColor)
            Y-=fontSize

            changes = changeset[fname]

            i=0
            firstChunk=True
            while i < len(changes):
                change = changes[i]
                #change is a ChangeSet

                ignoreThisChange=False
                for lineNumberToExclude in changesToIgnoreByFilename.get(os.path.basename(fname),[]):
                    if change.line1 <= lineNumberToExclude and lineNumberToExclude <= change.line2:
                        ignoreThisChange=True
                        break

                if ignoreThisChange:
                    i+=1
                    continue

                if change.type == ChangeType.NEW_CHUNK:
                    #draw separator
                    if firstChunk:
                        firstChunk=False
                    else:
                        drawChunkSeparator(Y)
                        Y -= fontSize/4
                        Y -= fontSize
                    checkIfPageIsFull()

                    numLineNumberDigits = 1+int(math.log10(max([change.line1,change.line2,1])))

                    if showContainingFunction:
                        filename1, filename2 = change.content
                        # ~ print("CHCO:",change.content)
                        # ~ containing1 = getContainingFunction(filename1, change.line1)
                        containing2 = getContainingFunction(filename2, change.line2)
                        if containing2:
                            checkIfPageIsFull()
                            preparePage()

                            w = reportlab.pdfbase.pdfmetrics.stringWidth(containing2,
                                containingFunctionFontName,
                                fontSize
                            )

                            t = cvs.beginText(pageWidth/2 - w/2, Y)
                            t.setFillColorRGB( *containingFunctionColor )
                            t.setFont( containingFunctionFontName, fontSize )
                            t.textOut(containing2)
                            cvs.drawText(t)

                            # ~ cvs.drawCentredString(pageWidth - w/2,Y,containing2)
                            Y -= fontSize





                elif change.type == ChangeType.DIFFERING_BINARY:
                    pass
                elif change.type == ChangeType.REMOVED_FILE:
                    pass
                elif change.type == ChangeType.ADDED_FILE:
                    pass
                elif change.type in (ChangeType.DELETED, ChangeType.INSERTED, ChangeType.CONTEXT):
                    if ignoreBlankLines and len(change.content.strip() ) == 0:
                        pass
                    else:
                        if change.type == ChangeType.DELETED:
                            outputText(change.content,change.line1,change.type)
                            Y -= fontSize
                        elif change.type == ChangeType.INSERTED:
                            outputText(change.content,change.line2,change.type)
                            Y -= fontSize
                        elif change.type == ChangeType.CONTEXT:
                            outputText(change.content,change.line2,change.type)
                            Y -= fontSize
                        else:
                            assert 0
                else:
                    assert 0

                i+=1

        endPage()

    print("Wrote",outputFile)
    cvs.save()


    return


def insertedEntireFile( fname, changeset ):

    if os.path.isdir(fname):
        for dirpath,dirs,files in os.walk(fname):
            for f in files:
                insertedEntireFile(os.path.join(dirpath,f), changeset)
        return

    assert fname not in changeset
    changeset[fname]=[]

    changeset[fname].append(
        ChangeInfo( type=ChangeType.ADDED_FILE,
                    line1=1,
                    line2=1,
                    content=fname
        )
    )

    with open(fname, errors="replace") as fp:
        data = fp.read()
    isBinary=False
    #if we have more than 50% of file is binary, note that fact
    numBin=0
    numAscii=0
    for c in data[:100]:
        if c.isascii() and c.isprintable():
            numAscii+=1
        else:
            numBin+=1
    totalChars = numBin+numAscii
    if totalChars > 0:
        if numBin / totalChars >= 0.5:
            data = "This file contains binary data"
    print(fname,"is",numBin,numAscii)

    lines = data.split("\n")
    for idx,txt in enumerate(lines):
        changeset[fname].append(
            ChangeInfo( type=ChangeType.INSERTED,
                        line1=1,
                        line2=idx+1,
                        content=txt
            )
        )

def getDifferences(dir1,dir2):
    os.putenv("DFT_UNSTABLE","yes")
    P = subprocess.Popen(
        [
            "diff",
            "--ignore-all-space",
            "--ignore-blank-lines",
            "-r",
            "--unified=3",
            "--minimal",
            dir1,
            dir2
        ],
        stdout=subprocess.PIPE
    )

    o,e = P.communicate()
    o = o.decode(errors="replace")

    #indexed by filename
    changeset = {}

    i=0
    o=o.split("\n")
    if len(o[-1]) == 0:
        o.pop()

    onlyInRex = re.compile(r"^Only in ([^:]+): (.+)")
    binaryRex = re.compile(r"Binary files (.*) and (.*) differ")

    while i<len(o):
        line = o[i]
        # ~ print(line)

        if line.startswith("diff "):
            i+=1
        elif line.startswith("Only in "):
            M = onlyInRex.search(line)
            assert M

            fname = os.path.join(M.group(1),M.group(2))

            # ~ print("Added",fname,": From 'Only in'")

            if M.group(1).startswith(dir2):
                #entire file was inserted
                insertedEntireFile( fname, changeset )
            elif M.group(1).startswith(dir1):
                #entire file was deleted
                assert fname not in changeset
                changeset[fname]=[]
                changeset[fname].append(
                    ChangeInfo( type=ChangeType.REMOVED_FILE,
                                line1=-1,
                                line2=-1,
                                content=fname
                    )
                )
            else:
                print("M=",M)
                print("M.group(1)=",M.group(1))
                print("dir1=",dir1)
                print("dir2=",dir2)
                assert 0,f"{line}"
            i+=1
        elif line.startswith("---"):
            line = line[4:].strip()
            fname1 = line.split("\t")[0]
            i+=1
            line = o[i]
            assert line.startswith("+++")
            line = line[4:].strip()
            fname2 = line.split("\t")[0]
            i+=1
            #fname = os.path.basename(fname1)
            fname = fname2
            assert fname not in changeset
            changeset[fname]=[]
            # ~ print("Added",fname,"from ---")

        elif line.startswith("@@ "):
            #change set
            #format:  @@ -file1spec +file2spec @@
            #spec can be:
            #       startline,count
            #       startline           <-- count is 1
            #Note: The counts include context (unchanged) lines
            spec = line[2:].strip().split()
            i+=1
            if "," in spec[0]:
                l,c = spec[0].split(",")
            else:
                l=spec[0]
                c=1
            assert l.startswith("-")
            lineNum1 = int(l[1:])
            if "," in spec[1]:
                l,c = spec[1].split(",")
            else:
                l=spec[1]
                c=1
            assert l.startswith("+")
            lineNum2 = int(l[1:])
            assert lineNum1 > 0,f"{spec[0]}"
            assert lineNum2 > 0,f"{spec[1]}"
            changeset[fname].append(
                ChangeInfo( type=ChangeType.NEW_CHUNK,
                            line1=lineNum1,
                            line2=lineNum2,
                            content=(fname1,fname2)
                )
            )
        elif line.startswith(" "):
            #unchanged context
            changeset[fname].append(
                ChangeInfo(
                    type=ChangeType.CONTEXT,
                    line1=lineNum1,
                    line2=lineNum2,
                    content=line[1:].rstrip()
                )
            )
            lineNum1+=1
            lineNum2+=1
            i+=1
        elif line.startswith("-"):
            #deleted content
            changeset[fname].append( ChangeInfo(
                type=ChangeType.DELETED,
                line1=lineNum1,
                line2=lineNum2,
                content=line[1:].rstrip()
            ))
            lineNum1+=1
            i+=1
        elif line.startswith("+"):
            #added content
            changeset[fname].append( ChangeInfo(
                type=ChangeType.INSERTED,
                line1=lineNum1,
                line2=lineNum2,
                content=line[1:].rstrip()
            ))
            lineNum2+=1
            i+=1
        elif line == "\\ No newline at end of file":
            i+=1
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            M = binaryRex.search(line)
            fname = M.group(1)
            #fname = os.path.basename(fname)
            assert fname not in changeset,f"{fname}  ::  {changeset.keys()}"
            changeset[fname] = [
                ChangeInfo(
                    type=ChangeType.DIFFERING_BINARY,
                    line1=0,
                    line2=0,
                    content=fname
                )
            ]
            # ~ print("Added",fname,"from binary differ")
            i+=1
        else:
            assert 0, f"-->{str(line)}<--"

    return changeset


main()




    #note: 0,0 is bottom left corner

    #cvs.line( x,y,x,y )
    #cvs.rect(x,y,w,h,stroke={0,1},fill={0,1})
    #cvs.drawString(x,y,txt)
    #cvs.drawRightString(x,y,txt)
    #cvs.drawCentredString(x,y,txt)
    #t = cvs.beginText(x,y)
    #t.setTextOrigin(x,y)   <-- sets location for next output
    #t.moveCursor(dx,dy)    <-- delta from start of current line
    #                       <-- y>0 = down
    #x=t.getX()
    #y=t.getY()
    #t.setCharSpace(s)  <-- s=floating point
    #t.setWordSpace(s)  <-- s=floating point
    #t.setLeading(s)
    #t.setRise(s)       <-- superscript/subscript
    #t.setFillColor(...)
    #t.setStrokeColor(...)
    #t.textOut(txt)
    #t.textLine(txt)
    #t.textLines(txt,trim=1)

    #cvs.drawText(t)
    #cvs.showPage  <-- resets all page state
    #cvs.setFillColorRGB(r,g,b)
    #cvs.setStrokeColorRGB(r,g,b)
    #cvs.setFont(fontname, size)
    #cvs.setLineWidth(w)
    #cvs.saveState()
    #cvs.restoreState()
    #w = reportlab.pdfbase.pdfmetrics.stringWidth(text,fontname,size)
    #line spacing is the height


    #P = reportlab.platypus.Paragraph("This is some text")
    #params: available width and height
    #returned: actual width and height required
    #w,h = P.wrap(200,400)
    #P.drawOn(cvs,0,400)     #canvas, x,y locations

#<font name="foo" color="bar" size="14">...</font>
#<b>...</b>
#<i>...</i>
