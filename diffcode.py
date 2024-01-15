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


#FIXME: Display containing function and/or class

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

def main():

    MACROS = "{pagenum} {numpages} {today} {path1} {path2} {paths}"
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", default="out.pdf", help="Output filename")
    parser.add_argument("--font", default="Courier", help="Font filename or name of builtin font")
    parser.add_argument("path1", help="First path to scan")
    parser.add_argument("path2", help="Second path to scan")
    parser.add_argument("--header-left", default="{paths}", help=f"Header left side. Macros: {MACROS}" )
    parser.add_argument("--header-right", default="Page {pagenum} of {numpages}", help=f"Header right side. Macros: {MACROS}" )
    parser.add_argument("--footer-left", default="{today}", help=f"Footer left side. Macros: {MACROS}" )
    parser.add_argument("--footer-right", default="", help=f"Footer right side. Macros: {MACROS}" )
    parser.add_argument("--font-size", default=10, help="Font size, in points")
    parser.add_argument("--top-margin", default=0.5, help="Margin from top of page to header")
    parser.add_argument("--ignore", action="append", help="Glob pattern for files to ignore")
    
    args = parser.parse_args()
    
    pageHeight = 11*72
    pageWidth = 8.5*72
    outputFile = args.o

    if not args.ignore:
        ignoreGlobs = [
            "*.assets.json", "*.nuget.*", "*.cache", "*.csproj.*", "*.editorconfig",
            "*.exe", "*.dll", "*.so", "*.o", "*.pdb"
        ]
    else:
        ignoreGlobs = args.ignore[:]
        
    normalFontFile = args.font
    # ~ boldFontFile = None
    # ~ italicFontFile = None
    # ~ boldItalicFontFile = None

    headerLeft = args.header_left
    headerRight = args.header_right
    footerLeft = args.footer_left
    footerRight = args.footer_right
    
    fontSize = float(args.font_size)

    headerMargin = float(args.top_margin)*72       #margin from top of page to header
    contentMarginTop = 0.75*72           #margin from top of page to content
    contentMarginBottom = 0.75*72           #margin from top of page to content
    footerMargin = 0.5*72       #margin from bottom of page to footer
    leftMargin = 0.5*72
    rightMargin = 0.5*72
    centerMargin = 0.125*72     #margin around dividing line

    centerX = 0.5*pageWidth

    colorInsertLineNumber = (0.3,0.8,0.3)
    colorDeleteLineNumber = (1.0,0.5,0.5)
    colorContextLineNumber = (0.5,0.5,1.0)
    colorContextText = (0.5,0.5,0.5)
    colorInsertedText = (0,0.5,0)
    colorDeletedText = (0.5,0,0)
    textColor = (0,0,0)
    marginLineColor = (1,1,0)
    chunkSeparatorColor = (0.5,0.5,0.5)
    filenameColor = (1,0.5,0)


    ignoreBlankLines=True
    dir1 = sys.argv[1]
    dir2 = sys.argv[2]

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
        pathdelta = os.path.sep.join(p1) + "→" +os.path.sep.join(p2)


    if "." in normalFontFile:
        reportlab.pdfbase.pdfmetrics.registerFont(
            reportlab.pdfbase.ttfonts.TTFont( "MyFontNormal", normalFontFile )
        )
        normalFontName = "MyFontNormal"
    else:
        normalFontName = normalFontFile

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


    tmp = datetime.date.today()
    today = tmp.strftime("%Y-%b-%d")

    ascent, descent = reportlab.pdfbase.pdfmetrics.getAscentDescent( normalFontName, fontSize)

    numPages=0

    pageIsOpen=False
    pageNum=1
    numLineNumberDigits=1       #FIXME


    def getHeaderAndFooter():
        tmp=[]
        for s in [headerLeft, headerRight, footerLeft, footerRight]:
            s = s.replace("{pagenum}", str(pageNum) )
            s = s.replace("{numpages}", str(numPages) )
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
        cvs.drawString(leftMargin, footerMargin, fl )
        cvs.drawRightString(pageWidth-rightMargin, footerMargin, fr )
        
        pageNum+=1
        if numPages < pageNum:
            numPages = pageNum

        cvs.setStrokeColorRGB(*marginLineColor)
        
        cvs.setLineWidth(0.5)
        cvs.line( leftMargin, pageHeight-contentMarginBottom,
                  pageWidth-rightMargin, pageHeight-contentMarginBottom
        )
        cvs.line( leftMargin, contentMarginTop,
                  pageWidth-rightMargin, contentMarginTop
        )
        cvs.setStrokeColorRGB(0,0,0)
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
        t.setFillColorRGB(*textColor)
        t.setStrokeColorRGB(*textColor)
        cvs.drawText(t)
        return t.getX() + leftMargin

    def drawStrikeoutsAndUnderlines(strikes,underlines):
        cvs.saveState()
        #FIXME: Set color and line width
        for x1,x2,y in strikes:
            cvs.line( x1,y,x2,y )
        #FIXME: Set color and line width
        for x1,x2,y in underlines:
            cvs.line( x1,y,x2,y )
        cvs.restoreState()

    def drawRect(x,y,w,h,color):
        cvs.saveState()
        cvs.setFillColorRGB(*color)
        cvs.rect(x,y,w,h,stroke=0,fill=1)
        cvs.restoreState()

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
        match(changeType):
            case ChangeType.INSERTED:
                fg = colorInsertedText
            case ChangeType.DELETED:
                fg = colorDeletedText
            case ChangeType.CONTEXT:
                fg = colorContextText
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

            if changeType == ChangeType.INSERTED and startDrawingLines:
                w = charWidth(c)
                drawRect(t.getX(),Y+descent,w,fontSize*0.95, (0.8,1,0.8) )

            x1 = t.getX()
            t.textOut(c)
            x2 = t.getX()


            if changeType == ChangeType.DELETED and startDrawingLines:
                strikes.append( (x1,x2,Y + fontSize * 0.4) )
            #if changeType == ChangeType.INSERTED and startDrawingLines:
            #    underlines.append( (x1,x2,t.getY()-0.07*fontSize ) )


        cvs.drawText(t)
        drawStrikeoutsAndUnderlines(strikes,underlines)

        strikes=[]
        underlines=[]

        #note: This function leaves Y at the last
        #line of text, so the caller must decrement Y
        #if more text is to be written
    #end function


    def drawChunkSeparator(Y):
        cvs.saveState()
        cvs.setStrokeColorRGB(*chunkSeparatorColor)
        drawLine( leftMargin, Y, pageWidth-rightMargin, Y, 0.5, chunkSeparatorColor, dash=[5,4] )
        cvs.restoreState()



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

            ignore=False
            for p in ignoreGlobs:
                if fnmatch.fnmatch(fname,p):
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
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameColor)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameColor)
            Y-=fontSize
            cvs.drawCentredString(pageWidth/2,Y,txt)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameColor)
            Y-=SPACE
            drawLine(leftMargin,Y,pageWidth-rightMargin,Y,0.5,filenameColor)
            Y-=fontSize

            changes = changeset[fname]

            i=0
            firstChange=True
            while i < len(changes):
                change = changes[i]
                #change is a ChangeSet

                if change.type == ChangeType.NEW_CHUNK:
                    #draw separator
                    if firstChange:
                        firstChange=False
                    else:
                        drawChunkSeparator(Y)
                        Y -= fontSize/4
                        Y -= fontSize
                    checkIfPageIsFull()

                    numLineNumberDigits = 1+int(math.log10(max([change.line1,change.line2,1])))

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


def getDifferences(dir1,dir2):
    os.putenv("DFT_UNSTABLE","yes")
    P = subprocess.Popen(
        [
            "diff",
            "--ignore-all-space",
            "-r",
            "--unified=3",
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
        elif line.startswith("Only in"):
            M = onlyInRex.search(line)
            assert M

            fname = os.path.join(M.group(1),M.group(2))
            assert fname not in changeset
            changeset[fname]=[]

            # ~ print("Added",fname,": From 'Only in'")

            if M.group(1) == dir2:
                #entire file was inserted
                changeset[fname].append(
                    ChangeInfo( type=ChangeType.ADDED_FILE,
                                line1=1,
                                line2=1,
                                content=fname
                    )
                )

                with open(os.path.join(fname), errors="replace") as fp:
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
            elif M.group(1) == dir1:
                #entire file was deleted
                changeset[fname].append(
                    ChangeInfo( type=ChangeType.REMOVED_FILE,
                                line1=1,
                                line2=1,
                                content=fname
                    )
                )
            else:
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
                            content=None
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
            print("Added",fname,"from binary differ")
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

